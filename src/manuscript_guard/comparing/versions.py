"""One version of a manuscript, read as `audit` reads a paper, for setting beside another.

A Markdown or text file is read as it is typed, a .docx as `audit` reads one
(`text.docx.read_docx_text`: its paragraphs a line each, its headings by their styles, its
tables cell by cell), and a LaTeX entry with the files it inputs, as the Markdown its document
prints (`text.latex.printed`), each line of that placed back at its `.tex` file and line, its
tables read cell by cell from the source (`auditing.latex`). A PDF is read as `audit` reads
one (`auditing.pdf`): its text a line of the PDF to a line, its sections from the lines that
hold a section's name alone, and no table and no figure, which are lines of text there; each
place in it is a page and a line.

What is kept of each: the text; its sections, each by its title as printed and its own text up
to the next heading; its tables, each with its label ("Table 2", "Table S1"), its caption and
its rows of cells; its figures, each with its label and caption; and the lines whose numbers
are no part of the prose, the reference list's and the tables', which are compared apart or
not at all.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

#: The formats `compare` reads, by suffix.
SUFFIXES = {".md": "Markdown", ".markdown": "Markdown", ".txt": "Markdown",
            ".docx": "Word", ".tex": "LaTeX", ".pdf": "PDF"}  # fmt: skip

#: A display item's label where a caption opens with one: "Table 2.", "**Figure 1**:",
#: "Supplementary Table 3", "Table S1", "Fig. 4".
_LABEL = re.compile(
    r"^[\s*_>#:]*(?:(?P<supp>supplementary|supplemental|suppl\.)\s+)?"
    r"(?P<kind>tables?|figures?|figs?\.)\s*(?P<s>S)?(?P<n>\d{1,3})(?![\d])(?P<letter>[a-z]?)\b",
    re.IGNORECASE,
)
#: What stands between a label and its caption's words.
_AFTER_LABEL = re.compile(r"^[\s*_.:|\N{EN DASH}\N{EM DASH}-]*")
#: Lines a caption is looked for above or below its table.
_REACH = 3


class Unreadable(Exception):
    """A version, a letter or a comments file that cannot be read. The message says why."""


@dataclass(frozen=True)
class Heading:
    #: The title as printed, without its number's marks; "" for the text before the first.
    title: str
    level: int
    #: The heading's line in the version's text, from 1; 0 for the text before the first.
    line: int
    #: Its own text, up to the next heading of any level.
    body: str


@dataclass(frozen=True)
class Display:
    """A table or a figure: its label, its caption's words, where it stands, and a table's
    rows of cells, the header first."""

    label: str | None
    caption: str
    path: Path
    line: int
    rows: tuple[tuple[str, ...], ...] = ()
    #: False where a table's cells stand in a file its float inputs that was not read: they
    #: are then not compared, and the table is never said to be the same.
    read: bool = True


@dataclass(frozen=True)
class Version:
    path: Path
    #: "Markdown", "Word" or "LaTeX".
    kind: str
    #: What is compared and quoted from: the whole text, a line of a paragraph each in a .docx.
    text: str
    sections: tuple[Heading, ...]
    tables: tuple[Display, ...]
    figures: tuple[Display, ...]
    #: The lines of `text` (from 1) of the reference list and the tables, whose numbers are
    #: not compared as the prose's.
    set_apart: frozenset[int] = frozenset()
    #: Of those, the tables' lines and their captions': read as prose where the other version
    #: is a PDF, whose tables cannot be set apart (`differences.prose`).
    table_lines: frozenset[int] = frozenset()
    #: The files read, a LaTeX entry's tree.
    files: tuple[Path, ...] = ()
    #: Where a line of `text` stands in the files, where that is not the line itself.
    #: What was not read of the version, each as a sentence: tables or figures LaTeX numbers
    #: in a way the reading does not count, which are then given no number.
    notes: tuple[str, ...] = ()
    placed: Callable[[int], tuple[Path, int | None]] | None = field(default=None,
                                                                    compare=False)
    #: A PDF's text as read (`auditing.pdf.PdfText`), whose lines are said as pages and lines.
    pdf: object = field(default=None, compare=False)

    def place(self, line: int) -> tuple[Path, int | None]:
        return self.placed(line) if self.placed is not None else (self.path, line)


def label_of(kind: str, supplementary: bool, number: str) -> str:
    """"Table 2", "Table S1" or "Figure 3": one name for each way a paper writes a label, so
    that "Supplementary Table 1" and "Table S1" are one table."""
    name = "Table" if kind.lower().startswith("tab") else "Figure"
    return f"{name} {'S' if supplementary else ''}{int(number)}"


def labelled(line: str) -> tuple[str, str] | None:
    """The label a caption opens with and the caption's words after it, or None."""
    found = _LABEL.match(line)
    if found is None:
        return None
    label = label_of(found["kind"], bool(found["supp"] or found["s"]), found["n"])
    rest = _AFTER_LABEL.sub("", line[found.end() :])
    return label, " ".join(rest.replace("**", "").split()).strip("*_ ")


def read_version(path: Path) -> Version:
    """`path` read as its suffix says. Raises Unreadable with what to say."""
    from manuscript_guard.audit import UnreadableText, read_text
    from manuscript_guard.text.docx import NotADocx

    suffix = path.suffix.lower()
    if path.is_dir():
        raise Unreadable(f"{path} is a folder: name the version's file, a .docx, .md or .tex "
                         "(a .tex is read with the files it inputs)")  # fmt: skip
    if not path.is_file():
        raise Unreadable(f"{path} does not exist")
    if suffix not in SUFFIXES:
        raise Unreadable(f"{path} is not a .docx, .md, .txt, .tex or .pdf, which is what "
                         "compare reads")  # fmt: skip
    try:
        if suffix == ".pdf":
            version = _pdf(path)
        elif suffix == ".docx":
            version = _word(path)
        elif suffix == ".tex":
            version = _latex(path)
        else:
            version = markdown_version(path, read_text(path))
    except (NotADocx, UnreadableText, OSError) as exc:
        raise Unreadable(f"{path} cannot be read: {exc}") from None
    if not re.search(r"[^\W\d_]", version.text):
        raise Unreadable(f"{path} holds no text to compare")
    return version


def _pdf(path: Path) -> Version:
    """A PDF as `audit` reads one (`auditing.pdf`): its sections from the lines that hold a
    section's name alone, its reference list set apart as the audit finds it, and no table
    and no figure."""
    from manuscript_guard.audit import pdf_spans
    from manuscript_guard.auditing.pdf import UnreadablePdf, read_pdf

    try:
        pdf = read_pdf(path)
    except UnreadablePdf as exc:
        raise Unreadable(str(exc)) from None
    # A structured abstract's headings under the Abstract where they can be placed exactly
    # (`PdfText.placed`), as a .docx's styles set them.
    placed = pdf.placed
    found = ([(title, level, line) for line, title, level in placed] if placed is not None
             else [(title, 1, line) for line, title in pdf.headings])  # fmt: skip
    references = {line + 1 for start, end in pdf_spans(pdf) for line in range(start, end)}
    return Version(path, "PDF", pdf.text, _sections(pdf.text, found), (), (),
                   frozenset(references), pdf=pdf)


def _sections(text: str, found: list[tuple[str, int, int]]) -> tuple[Heading, ...]:
    """The sections of `text` from its headings (title, level, line), each with its own text
    up to the next; the text before the first heading as a section of no title."""
    from manuscript_guard.text.section_names import plain

    lines = text.split("\n")
    starts = [line for _title, _level, line in found]
    sections = []
    first = starts[0] if starts else len(lines) + 1
    before = "\n".join(lines[: first - 1])
    if before.strip():
        sections.append(Heading("", 0, 0, before))
    for at, (title, level, line) in enumerate(found):
        end = starts[at + 1] - 1 if at + 1 < len(starts) else len(lines)
        sections.append(Heading(plain(title), level, line, "\n".join(lines[line:end])))
    return tuple(sections)


def markdown_version(path: Path, text: str) -> Version:
    """A Markdown or text file's version, from its text."""
    from manuscript_guard.audit import bibliography_spans
    from manuscript_guard.text.blocks import scannable
    from manuscript_guard.text.sections import split_sections
    from manuscript_guard.text.tables import markdown_tables

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    found = [(s.title, s.level, s.line) for s in split_sections(scannable(text)) if s.level]
    lines = text.split("\n")
    tables = []
    in_tables: set[int] = set()
    for table in markdown_tables(text):
        rows = tuple(tuple(cell.text.strip() for cell in row) for row in table)
        first, last = table[0][0].line, table[-1][0].line
        in_tables.update(range(first, last + 1))
        label, caption, at = _caption(lines, first, last)
        in_tables.update({at} if at else set())
        tables.append(Display(label, caption, path, first, rows))
    references = {line + 1 for start, end in bibliography_spans(text)
                  for line in range(start, end)}  # fmt: skip
    return Version(path, "Markdown", text, _sections(text, found), tuple(tables),
                   _figures(lines, path, in_tables), frozenset(in_tables | references),
                   table_lines=frozenset(in_tables))


def _caption(lines: list[str], first: int, last: int) -> tuple[str | None, str, int]:
    """The label and caption of the table on lines `first` to `last` (from 1), and the line
    of its caption: the nearest line above that opens with a table's label, or below it
    pandoc's `: caption` or `Table: caption`; 0 where there is none. A line of nothing but
    a cell's edge, as a .docx's row is read, is passed over."""
    for at in range(first - 1, max(0, first - 1 - _REACH), -1):
        line = lines[at - 1]
        if not line.strip(" \t|"):
            continue
        found = labelled(line)
        if found and found[0].startswith("Table"):
            return found[0], found[1], at
        break
    for at in range(last + 1, min(len(lines), last + _REACH) + 1):
        line = lines[at - 1].strip()
        if not line:
            continue
        pandoc = re.match(r"^(?:Table)?:\s+(.*)$", line)
        if pandoc is None:
            break
        found = labelled(pandoc[1])
        if found and found[0].startswith("Table"):
            return found[0], found[1], at
        return None, " ".join(pandoc[1].split()), at
    return None, "", 0


def _figures(lines: list[str], path: Path, skipped: set[int]) -> tuple[Display, ...]:
    """Each figure by its caption, a line that opens with a figure's label, an image's
    description among them (`![Figure 2. ...](...)`)."""
    found = []
    for at, line in enumerate(lines, 1):
        if at in skipped:
            continue
        said = re.sub(r"^\s*!\[", "", line)
        said = re.sub(r"\]\([^)]*\)\s*$", "", said) if said != line else said
        label = labelled(said)
        if label and label[0].startswith("Figure"):
            found.append(Display(label[0], label[1], path, at))
    return tuple(found)


def _word(path: Path) -> Version:
    """A .docx as `audit` reads one."""
    from manuscript_guard.audit import bibliography_spans
    from manuscript_guard.text.docx import read_docx_text

    document = read_docx_text(path)
    text = document.text
    body = document.body.split("\n")
    found = [(body[at], level, at + 1) for at, level in document.heading_levels]
    spans = bibliography_spans(document.body, document.headings, document.cells)
    references = {line + 1 for start, end in spans for line in range(start, end)}
    lines = text.split("\n")
    cells = {at + 1 for at in document.cells}
    tables = []
    for table in document.tables:
        if not table or not table[0]:
            continue
        first, last = table[0][0].line, table[-1][0].line
        if any(first in range(start + 1, end + 1) for start, end in spans):
            continue
        label, caption, at = _caption(lines, first, last)
        rows = tuple(tuple(cell.text.strip() for cell in row) for row in table)
        tables.append(Display(label, caption, path, first, rows))
        if at:
            cells.add(at)
    return Version(path, "Word", text, _sections(text, found), tuple(tables),
                   _figures(lines, path, cells), frozenset(cells | references),
                   table_lines=frozenset(cells))


# ------------------------------------------------------------------------------- LaTeX

#: A file input, whose text a float holding it prints.
_INPUT = re.compile(r"\\(?:input|include|subfile|import|subimport)(?![A-Za-z@])")
_COMMAND = re.compile(r"\\[A-Za-z@]+\*?(?:\s*\[[^\]]*\])?|[{}~]")


def _latex(path: Path) -> Version:
    """A LaTeX entry and the files it inputs, as the Markdown its document prints."""
    from manuscript_guard.auditing.latex import read_latex
    from manuscript_guard.text.blocks import scannable
    from manuscript_guard.text.latex.printed import printed
    from manuscript_guard.text.sections import split_sections

    read = read_latex([path])
    if not read.trees:
        raise Unreadable(f"{path} starts no document: it has no \\documentclass")
    tree = read.trees[0]
    sources = [source for _path, source in tree.files
               if not source.path.lower().endswith(".sty")]  # fmt: skip
    view = printed(sources, quoting=True)
    text = view.text
    found = [(s.title, s.level, s.line) for s in split_sections(scannable(text)) if s.level]

    def placed(line: int) -> tuple[Path, int | None]:
        where = view.place_line(line)
        if where is None:
            return path, None
        source, at = where
        return tree.folder / source.path, at

    tables, figures, notes = _floats(tree, {file.path: file.tables for file in read.files})
    return Version(path, "LaTeX", text, _sections(text, found), tables, figures,
                   files=tuple(p for p, _source in tree.files), notes=notes, placed=placed)


#: What is said of a version whose tables or figures are not numbered here.
NOT_NUMBERED = (
    "its {kinds} are not numbered here: a {kind} LaTeX numbers in a way this reading does not "
    "count stands among them (a longtable's caption, a \\captionof, or a float whose caption "
    "is not read), so each is matched by its caption alone"
)


@dataclass
class _Shown:
    """A display the printed view numbers, as the walk finds it."""

    kind: str
    counted: bool
    caption: str
    path: Path
    line: int
    rows: tuple[tuple[str, ...], ...] = ()
    read: bool = True


def _floats(tree, read: dict) -> tuple[tuple[Display, ...], tuple[Display, ...], tuple[str, ...]]:
    """Each table and figure of the tree, in the order the document prints them, as the
    printed view G2's pointers read numbers them (`printed._pointing_events`): a float of
    each kind `commands.FLOATS` lists, one display for each caption, none for a float
    continued from the last, and a file input where its `\\input` stands, inside a float as
    that float's. Each table with its cells, its own or those of a file its float inputs,
    where the float holds one table this reading pairs with its one caption; else with
    none, said so. Where the view
    cannot count a display of a kind, a longtable's caption or a `\\captionof`, none of
    that kind is numbered, and a note says so. A table typed outside every display has no
    label."""
    by_path = {source.path: (path, source) for path, source in tree.files}
    entry = next((source.path for path, source in tree.files if path == tree.entry),
                 tree.files[0][1].path if tree.files else None)  # fmt: skip
    held = {path: list(read.get(path, ())) for path, _source in tree.files}
    shown: list[_Shown] = []
    seen: set[str] = set()

    def walk(name: str, inside: _Shown | None) -> None:
        if name in seen or name not in by_path:
            return
        seen.add(name)
        path, source = by_path[name]
        mine = _displays(path, source, held)
        events = [(at, 0, target) for at, target in source.targets]
        events += [(start, 1, display) for start, _end, display in mine]
        for at, step, what in sorted(events, key=lambda event: (event[0], event[1])):
            if step == 0:
                around = next((d for start, end, d in mine if start <= at < end
                               and d.kind == "t"), inside)  # fmt: skip
                # A file read already, by another float, or not read at all, gives this one
                # nothing that is its own.
                if around is not None and (what in seen or what not in by_path):
                    around.read = False
                walk(what, around)
            else:
                shown.append(what)
        # A file read inside a float: its one table is that float's; two, or one beside the
        # float's own, are not told apart, and the float's cells are not read.
        if inside is not None and held[path]:
            if len(held[path]) == 1 and not inside.rows and inside.read:
                inside.rows = _rows_of(held[path][0])
            else:
                inside.read = False
            held[path] = []

    if entry is not None:
        walk(entry, None)
    for display in shown:
        if display.kind == "t" and not display.rows:
            display.read = False
    tables = _numbered([d for d in shown if d.kind == "t"], "Table")
    figures = _numbered([d for d in shown if d.kind == "f"], "Figure")
    notes = tuple(NOT_NUMBERED.format(kinds=kinds, kind=kinds[:-1])
                  for displays, kinds in ((tables, "tables"), (figures, "figures"))
                  if displays and displays[0].label is None)  # fmt: skip
    for path, _source in tree.files:
        tables += [Display(None, "", path, table[0][0].line, _rows_of(table))
                   for table in held[path] if table]  # fmt: skip
    return tuple(tables), tuple(figures), notes


def _rows_of(table) -> tuple[tuple[str, ...], ...]:
    return tuple(tuple(cell.text.strip() for cell in row) for row in table)


def _numbered(displays: list[_Shown], name: str) -> list[Display]:
    """The displays of one kind, each given its number, or none where any of them is one the
    view cannot count."""
    every = all(display.counted for display in displays)
    return [Display(f"{name} {at}" if every else None, display.caption, display.path,
                    display.line, display.rows, display.read)
            for at, display in enumerate(displays, 1)]  # fmt: skip


def _displays(path: Path, source, held: dict) -> list[tuple[int, int, _Shown]]:
    """Each display one file writes in the printed view G2's pointers read, where it stands
    in the file, with its caption and, where the display is a float's one table display and
    the float holds one table, that table's cells; otherwise its cells are not read."""
    from manuscript_guard.text.latex.printed import (
        DISPLAY,
        MARK_END,
        _numbered_captions,
        _passed_over,
        _pointing_events,
    )

    marks = re.compile(f"{DISPLAY}([^{MARK_END}]*){MARK_END}")
    is_read, comments = _passed_over(source.reading)
    text = source.text
    found = []
    for start, end, written in _pointing_events(source):
        kinds = [mark[:1] for mark in marks.findall(written) if mark[:1] in "tfTF"]
        if not kinds:
            continue
        captions = [_braced(text, opened + 1) for _begun, opened, _closed
                    in _numbered_captions(text, start, end, is_read, comments)]  # fmt: skip
        first, last = text.count("\n", 0, start) + 1, text.count("\n", 0, end) + 1
        inputs = sum(1 for one in _INPUT.finditer(text, start, end) if is_read(one.start()))
        targets = sum(1 for at, _name in source.targets if start <= at < end)
        cells = [table for table in held[path] if table and first <= table[0][0].line <= last]
        held[path] = [table for table in held[path] if table not in cells]
        # One table display and one table, its own or the one file it inputs: the table is
        # the display's. Any other count, two captions over two tables, one over two, is not
        # one to one, and which table a caption numbers is not read.
        one = sum(kind in "tT" for kind in kinds) == 1 and (
            (len(cells) == 1 and not inputs) or (not cells and inputs == targets == 1))
        for at, kind in enumerate(kinds):
            shown = _Shown(kind.lower(), kind.islower(), captions[at] if at < len(captions)
                           else "", path, first)  # fmt: skip
            if shown.kind == "t":
                shown.read = one
                shown.rows = _rows_of(cells[0]) if one and cells else ()
            found.append((start, end, shown))
    return found


def _braced(text: str, opened: int) -> str:
    """The argument whose brace opens just before `opened`, its commands and braces taken
    out."""
    depth, at = 1, opened
    while at < len(text) and depth:
        depth += {"{": 1, "}": -1}.get(text[at], 0) if text[at - 1] != "\\" else 0
        at += 1
    said = re.sub(r"\\(?:label|ref|cite[a-z]*)\s*\{[^{}]*\}", " ", text[opened : at - 1])
    return " ".join(_COMMAND.sub(" ", said).split())
