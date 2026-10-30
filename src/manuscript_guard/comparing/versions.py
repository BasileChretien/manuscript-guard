"""One version of a manuscript, read as `audit` reads a paper, for setting beside another.

A Markdown or text file is read as it is typed, a .docx as `audit` reads one
(`text.docx.read_docx_text`: its paragraphs a line each, its headings by their styles, its
tables cell by cell), and a LaTeX entry with the files it inputs, as the Markdown its document
prints (`text.latex.printed`), each line of that placed back at its `.tex` file and line, its
tables read cell by cell from the source (`auditing.latex`). A PDF is not read.

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
            ".docx": "Word", ".tex": "LaTeX"}  # fmt: skip

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
    #: The files read, a LaTeX entry's tree.
    files: tuple[Path, ...] = ()
    #: Where a line of `text` stands in the files, where that is not the line itself.
    placed: Callable[[int], tuple[Path, int | None]] | None = field(default=None,
                                                                    compare=False)

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
    if suffix == ".pdf":
        raise Unreadable(f"{path} is a PDF, which compare does not read yet: ask the editor for "
                         "the manuscript's source, a .docx, .md or .tex")  # fmt: skip
    if path.is_dir():
        raise Unreadable(f"{path} is a folder: name the version's file, a .docx, .md or .tex "
                         "(a .tex is read with the files it inputs)")  # fmt: skip
    if not path.is_file():
        raise Unreadable(f"{path} does not exist")
    if suffix not in SUFFIXES:
        raise Unreadable(f"{path} is not a .docx, .md, .txt or .tex, which is what compare "
                         "reads")  # fmt: skip
    try:
        if suffix == ".docx":
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
                   _figures(lines, path, in_tables), frozenset(in_tables | references))


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
                   _figures(lines, path, cells), frozenset(cells | references))


# ------------------------------------------------------------------------------- LaTeX

#: A float, and a caption in it.
_FLOAT = re.compile(r"\\begin\s*\{(?P<kind>table|figure)\*?\}(?P<body>.*?)\\end\s*\{(?P=kind)\*?\}",
                    re.DOTALL)  # fmt: skip
#: A `longtable`, which numbers a table where it has a caption; and a `\\captionof`.
_LONGTABLE = re.compile(r"\\begin\s*\{longtable\}.*?\\end\s*\{longtable\}", re.DOTALL)
_CAPTIONOF = re.compile(
    r"\\captionof\s*\{\s*(?P<kind>table|figure)\s*\}\s*(?:\[[^\]]*\])?\s*\{"
)
_CAPTION = re.compile(r"\\caption\s*(?:\[[^\]]*\])?\s*\{")
_COMMENT = re.compile(r"(?<!\\)%[^\n]*")
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

    tables, figures = _floats(tree, {file.path: file.tables for file in read.files})
    return Version(path, "LaTeX", text, _sections(text, found), tables, figures,
                   files=tuple(p for p, _source in tree.files), placed=placed)


def _floats(tree, read: dict) -> tuple[tuple[Display, ...], tuple[Display, ...]]:
    """Each table and figure of the tree that LaTeX numbers, in the order the document prints
    them: a float with a caption, a `longtable` with one, and a `\\captionof{table}` or
    `{figure}` outside a float, each file read where the file that inputs it inputs it. Each
    table with its cells where the audit read a table in it; and a table typed outside any
    of them, with no label."""
    by_path = {source.path: (path, source) for path, source in tree.files}
    entry = next((source.path for path, source in tree.files if path == tree.entry),
                 tree.files[0][1].path if tree.files else None)  # fmt: skip
    tables: list[Display] = []
    figures: list[Display] = []
    held = {path: list(read.get(path, ())) for path, _source in tree.files}
    seen: set[str] = set()

    def walk(name: str) -> None:
        if name in seen or name not in by_path:
            return
        seen.add(name)
        path, source = by_path[name]
        text = _COMMENT.sub(lambda m: " " * len(m.group()), source.text)
        events = [(at, "input", target) for at, target in source.targets]
        events += [(start, kind, (start, end, caption)) for start, end, kind, caption
                   in _numbered(text)]  # fmt: skip
        for _at, kind, what in sorted(events, key=lambda event: event[0]):
            if kind == "input":
                walk(what)
                continue
            start, end, caption = what
            first = text.count("\n", 0, start) + 1
            last = text.count("\n", 0, end) + 1
            if kind == "figure":
                figures.append(Display(f"Figure {len(figures) + 1}", caption, path, first))
                continue
            inside = [table for table in held[path] if table and first <= table[0][0].line <= last]
            held[path] = [table for table in held[path] if table not in inside]
            rows = (tuple(tuple(cell.text.strip() for cell in row) for row in inside[0])
                    if inside else ())  # fmt: skip
            tables.append(Display(f"Table {sum(t.label is not None for t in tables) + 1}",
                                  caption, path, first, rows))  # fmt: skip

    if entry is not None:
        walk(entry)
    for path, _source in tree.files:
        tables += [Display(None, "", path, table[0][0].line,
                           tuple(tuple(cell.text.strip() for cell in row) for row in table))
                   for table in held[path] if table]  # fmt: skip
    return tuple(tables), tuple(figures)


def _numbered(text: str) -> list[tuple[int, int, str, str]]:
    """Where each table and figure LaTeX numbers stands in one file, its kind and caption: a
    float or a `longtable` with a caption, and a `\\captionof` outside them."""
    found = []
    spans = []
    for match in _FLOAT.finditer(text):
        spans.append((match.start(), match.end()))
        caption = _caption_of(match["body"])
        if caption is not None:
            found.append((match.start(), match.end(), match["kind"], caption))
    for match in _LONGTABLE.finditer(text):
        spans.append((match.start(), match.end()))
        caption = _caption_of(match.group())
        if caption is not None:
            found.append((match.start(), match.end(), "table", caption))
    for match in _CAPTIONOF.finditer(text):
        if any(start <= match.start() < end for start, end in spans):
            continue
        found.append((match.start(), match.end(), match["kind"], _braced(text, match.end())))
    return found


def _caption_of(body: str) -> str | None:
    """A float's caption, its commands and braces taken out, or None where it has none."""
    found = _CAPTION.search(body)
    return None if found is None else _braced(body, found.end())


def _braced(text: str, opened: int) -> str:
    """The argument whose brace opens just before `opened`, its commands and braces taken
    out."""
    depth, at = 1, opened
    while at < len(text) and depth:
        depth += {"{": 1, "}": -1}.get(text[at], 0) if text[at - 1] != "\\" else 0
        at += 1
    said = re.sub(r"\\(?:label|ref|cite[a-z]*)\s*\{[^{}]*\}", " ", text[opened : at - 1])
    return " ".join(_COMMAND.sub(" ", said).split())
