"""A paper written in Word, brought into a project: `init --from paper.docx`.

pandoc reads the document into its tree, with tracked changes accepted. Three things are
changed in the tree before pandoc writes it as Markdown, and nothing else:

- Each table whose cells hold only paragraphs is written as a pipe table, which every reader
  here reads as rows of cells: a cell's paragraphs and line breaks are joined with spaces, a
  merged cell's text stands in its first row and column with the cells it covered left
  empty, and a second header row or a footer row becomes a row of the body. As pandoc writes
  a Word table by default, most are multiline tables, whose lines of dashes `check` refuses
  at every stage (`rule-opens-a-block`). A table with anything else in a cell, a list or
  another table, is written as a grid table, whose rows `check` reads as a table's and whose
  cells the audit does not read, and is named in what `init` prints. None is dropped.
- The pictures are saved in `manuscript/media/`, and each image points there.
- What stands before the first heading, the title page, is set aside in one HTML comment at
  the top of `main.md`: it is kept, and no gate reads it. Only where it is short enough to
  be one (`TITLE_PAGE_WORDS`); a longer run before the first heading is the paper's text, an
  introduction with no heading over it, and stays in it.

What pandoc reads from Word's Title, Author, Date and Abstract styles is its metadata. The
title goes to `paper.yaml`, each author's name to `authors.yaml` as the paper gives it, and
the abstract becomes the manuscript's `# Abstract`. A Title paragraph holding a note, a mark,
a link or a picture, which its plain text loses, is in the comment as well; the marks of
notes raised at its end are left out of the title, and kept there with it. Nothing is
guessed from how a line looks: a name in capitals is a line of the title page like any other.
"""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from manuscript_guard.contracts._schema import ContractError

#: The first bytes of a Word 97-2003 document, an OLE compound file, which pandoc cannot read.
LEGACY_DOC = b"\xd0\xcf\x11\xe0"
#: The first bytes of a zip archive, which a .docx is.
ZIP = b"PK\x03\x04"
#: The most words set aside as a title page: a title, a long list of authors with their
#: affiliations, and an abstract of 300 words come to less. An introduction with no heading
#: above it, as APA style writes one, comes to more, and is left in the text.
TITLE_PAGE_WORDS = 600
#: Where the pictures go, from the project's root. Not `figures/`: that folder holds what an
#: analysis rendered, and every file in it is checked as such.
MEDIA = "manuscript/media"
#: Simple and multiline tables off, so that a table of single-line cells is written as a pipe
#: table and any other as a grid table. With pandoc's default line of 72 columns, a table of
#: more than nine columns is too wide for a grid and was written as raw HTML: the widths are
#: left to the cells, and the line made long enough for any table.
WRITER = ["-t", "markdown-simple_tables-multiline_tables", "--wrap=none", "--columns=100000"]
#: The longest pandoc is given to read or write one paper.
PANDOC_SECONDS = 300

_JOINED = {"Para", "Plain", "Header", "LineBlock", "BlockQuote", "Div"}
_KIND = {
    "BulletList": "a list",
    "OrderedList": "a numbered list",
    "DefinitionList": "a list",
    "Table": "a table",
    "CodeBlock": "a block of code",
    "Figure": "a figure",
    "RawBlock": "raw markup",
    "HorizontalRule": "a rule",
}
_SPACE = {"t": "Space"}
_NO_ATTR = ["", [], []]


@dataclass(frozen=True)
class Converted:
    """A Word paper as `init` writes it."""

    title: str | None
    authors: tuple[str, ...]
    abstract: bool
    text: str
    media: tuple[tuple[str, bytes], ...]
    tables: int
    tables_left: tuple[str, ...]
    title_page: str
    headings: int
    #: The Title paragraph holds what its plain text leaves out, and is in the comment too.
    title_noted: bool = False
    #: The footnote marks at the Title paragraph's end, left out of `title`.
    title_marks: str = ""


def refused(path: Path) -> str | None:
    """Why `path` is not read as a .docx, or None where it is one."""
    try:
        with path.open("rb") as handle:
            start = handle.read(4)
    except OSError as exc:
        return f"{path} could not be read: {exc.strerror or exc}"
    if start == LEGACY_DOC:
        return (f"{path} is a Word 97-2003 document (.doc), which pandoc cannot read: "
                "open it in Word and save it as .docx")  # fmt: skip
    if start != ZIP:
        return f"{path} is not a .docx: a Word document is a zip archive, and this is not one"
    return None


def convert(path: Path, *, titled: bool = False) -> Converted:
    """The paper at `path`, converted. Raises ContractError where it cannot be read. With
    `titled`, the title was given otherwise, and the Title paragraph is set aside."""
    path = Path(path)
    why = refused(path)
    if why is not None:
        raise ContractError(why)
    with tempfile.TemporaryDirectory(prefix="mg-docx-") as folder:
        tree = json.loads(_pandoc([str(path.resolve()), "-f", "docx", "-t", "json",
                                   f"--extract-media={folder}"], None, path))  # fmt: skip
        media = _pictures(tree, Path(folder))
    meta = tree.get("meta", {})
    unmarked, marks = (None, "") if titled else _without_marks(meta.get("title"))
    title = _plain_title(unmarked)
    # The Title paragraph stays in the metadata, and so goes into the comment, where `--title`
    # gives the title or where its plain text leaves something out: a note on the title names
    # the funder or the corresponding author, and was written nowhere.
    noted = not titled and "title" in meta and _marked(meta["title"])
    if not titled and not noted:
        meta.pop("title", None)
    names, others = _names(meta.pop("author", None))
    abstract = _as_blocks(meta.pop("abstract", None))
    blocks = tree["blocks"]
    headings = sum(1 for block in blocks if block["t"] == "Header")
    aside, body, title_page = _title_page(blocks)
    if abstract:
        body = [_heading("Abstract"), *abstract, *body]
    converted, unconverted = _tables(body)
    left = tuple(f"{said}; {_form(_write(tree, [table], path))}"
                 for said, table in unconverted)  # fmt: skip
    aside = [*_leftovers(meta, others), *aside]
    text = _comment(_write(tree, aside, path)) + _write(tree, body, path)
    return Converted(title=title, authors=names, abstract=bool(abstract), text=text,
                     media=media, tables=converted, tables_left=left, title_page=title_page,
                     headings=headings, title_noted=noted,
                     title_marks=marks)  # fmt: skip


def _pandoc(arguments: list[str], given: str | None, path: Path) -> str:
    from manuscript_guard.build.document import BuildError, pandoc

    try:
        command = [pandoc(), *arguments]
    except BuildError as exc:
        raise ContractError(f"{exc}; init needs it to read {path.name}") from None
    try:
        finished = subprocess.run(
            command, input=None if given is None else given.encode("utf-8"),
            capture_output=True, timeout=PANDOC_SECONDS, check=False,
        )  # fmt: skip
    except subprocess.TimeoutExpired:
        raise ContractError(f"pandoc did not finish {path.name} within {PANDOC_SECONDS} s; "
                            "nothing was made") from None  # fmt: skip
    if finished.returncode != 0:
        said = finished.stderr.decode("utf-8", errors="replace").strip()
        raise ContractError(f"pandoc could not convert {path.name}, so nothing was made: {said}")
    return finished.stdout.decode("utf-8")


def _write(tree: dict, blocks: list, path: Path) -> str:
    """The blocks as pandoc writes them in Markdown, a paragraph to a line."""
    if not blocks:
        return ""
    document = {"pandoc-api-version": tree["pandoc-api-version"], "meta": {}, "blocks": blocks}
    return _pandoc(["-f", "json", *WRITER], json.dumps(document), path)


def _comment(markdown: str) -> str:
    """What is set aside, in one HTML comment that nothing in it can close."""
    if not markdown.strip():
        return ""
    kept = markdown.strip().replace("-->", "--&gt;")
    return (
        "<!--\nSet aside by `manuscript-guard init --from`: what stood before the first "
        "heading of the Word document, and what its title styles held that paper.yaml and "
        "authors.yaml do not. No gate reads this comment and the build does not print it. "
        "Move into the text below anything that belongs to the paper, an abstract for one.\n\n"
        f"{kept}\n-->\n\n"
    )


def _pictures(tree: dict, folder: Path) -> tuple[tuple[str, bytes], ...]:
    """Each picture pandoc saved under `folder`, by its path in the project, with every image
    pointed at that path. pandoc saves them in `media/`, which the path in the project leaves
    out; one saved elsewhere in `folder` keeps the rest of its path, so that no image points
    into `folder`, which is deleted once read. An image that points outside `folder`, a web
    address, was not saved by pandoc and is left as it is."""
    base = folder.resolve()
    found: dict[str, bytes] = {}
    whence: dict[str, Path] = {}
    for image in _walk([*tree.get("meta", {}).values(), tree["blocks"]], "Image"):
        target = Path(image["c"][2][0])
        try:
            inside = target.resolve().relative_to(base)
        except (ValueError, OSError):
            continue
        parts = inside.parts[1:] if inside.parts[:1] == ("media",) else inside.parts
        name = "/".join([MEDIA, *parts])
        if name not in found:
            found[name] = target.read_bytes()
            whence[name] = inside
        elif whence[name] != inside:
            raise ContractError(f"pandoc saved two pictures of the Word paper that would both "
                                f"be {name}; nothing was made")  # fmt: skip
        image["c"][2][0] = name
    return tuple(sorted(found.items()))


def _walk(node: object, kind: str):
    """Each element of `kind` in the tree, outermost first."""
    if isinstance(node, dict):
        if node.get("t") == kind:
            yield node
        yield from _walk(node.get("c"), kind)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item, kind)


#: The blocks whose text ends with a space, so that two of them do not run together.
_BLOCKS = frozenset({"Para", "Plain", "Header", "LineBlock", "CodeBlock"})


def text_of(node: object) -> str:
    """What a piece of pandoc's tree says, as plain text: a picture's description and a
    note's text are left out, and an identifier or a link's address is not text."""
    if isinstance(node, list):
        return "".join(text_of(item) for item in node)
    if not isinstance(node, dict):
        return ""
    kind = node.get("t")
    if kind in ("Str", "MetaString"):
        return node["c"]
    if kind in ("Space", "SoftBreak", "LineBreak"):
        return " "
    if kind in ("Code", "Math", "RawInline", "CodeBlock"):
        return node["c"][1] + (" " if kind == "CodeBlock" else "")
    if kind in ("Image", "Note"):
        return ""
    inner = text_of(node.get("c"))
    return inner + " " if kind in _BLOCKS else inner


def _words(blocks: list) -> int:
    return len(text_of(blocks).split())


def _plain_title(value: dict | None) -> str | None:
    """The Title paragraph as plain text: its pictures and notes left out, its lines joined."""
    if value is None:
        return None
    title = " ".join(text_of(value).split())
    return title or None


#: A superscript that is a footnote's mark: digits or the usual signs, several with commas.
_MARK = re.compile(r"[\d*†‡§¶‖#]+(?:\s*,\s*[\d*†‡§¶‖#]+)*")
#: What stands between two marks, in the line rather than raised with them.
_BETWEEN = re.compile(r"\s*,\s*")
_GAPS = frozenset({"Space", "SoftBreak", "LineBreak"})


def _without_marks(value: dict | None) -> tuple[dict | None, str]:
    """The Title paragraph without the footnote marks at its end, and those marks as they
    read. `text_of` keeps a superscript's text and glues it on, and "a fall¹" was the title
    "a fall1". Only a superscript at the end, of digits or the usual signs, is taken for a
    mark: "CD4⁺ T cells", "Na⁺" and a superscript inside the title are the title's."""
    if value is None:
        return None, ""
    value = json.loads(json.dumps(value))
    if value.get("t") == "MetaInlines":
        inlines = value["c"]
    elif value.get("t") == "MetaBlocks" and value["c"] and value["c"][-1]["t"] in ("Para", "Plain"):
        inlines = value["c"][-1]["c"]
    else:
        return value, ""
    end = _trimmed(inlines, len(inlines))
    cut = end
    while cut and _is_mark(inlines[cut - 1]):
        cut = _trimmed(inlines, cut - 1)
        if cut and inlines[cut - 1]["t"] == "Str" and _BETWEEN.fullmatch(inlines[cut - 1]["c"]):
            further = _trimmed(inlines, cut - 1)
            if further and _is_mark(inlines[further - 1]):
                cut = further
    if cut == end or not text_of(inlines[:cut]).strip():
        return value, ""
    marks = text_of(inlines[cut:end]).strip()
    del inlines[cut:]
    return value, marks


def _trimmed(inlines: list, end: int) -> int:
    while end and inlines[end - 1]["t"] in _GAPS:
        end -= 1
    return end


def _is_mark(inline: dict) -> bool:
    return inline["t"] == "Superscript" and bool(_MARK.fullmatch(text_of(inline).strip()))


#: What `text_of` leaves out of a paragraph, or keeps only part of: a note, a picture, a
#: link's address. A superscript is kept as text, but stands for a mark.
_DROPPED = ("Superscript", "Note", "Image", "Link")


def _marked(value: object) -> bool:
    """Whether `value` holds something its plain text does not carry whole."""
    return any(next(_walk(value, kind), None) for kind in _DROPPED)


#: What a name does not hold: a list of several, an affiliation's number or mark, a note.
_NOT_A_NAME = re.compile(r"[,;&*†‡§\d]|\band\b", re.IGNORECASE)


def _names(value: dict | None) -> tuple[tuple[str, ...], list]:
    """The names of Word's Author paragraphs, one name each, and the paragraphs that are not
    one name, which are set aside with the title page."""
    if value is None:
        return (), []
    entries = value["c"] if value.get("t") == "MetaList" else [value]
    names: list[str] = []
    others: list = []
    for entry in entries:
        said = " ".join(text_of(entry).split())
        if not said:
            continue
        if _marked(entry) or _NOT_A_NAME.search(said):
            others.append(entry)
        else:
            names.append(said)
    return tuple(names), others


def _as_blocks(value: dict | None) -> list:
    if value is None:
        return []
    if value.get("t") == "MetaBlocks":
        return value["c"]
    if value.get("t") == "MetaInlines":
        return [{"t": "Para", "c": value["c"]}]
    if value.get("t") == "MetaList":
        return [block for item in value["c"] for block in _as_blocks(item)]
    if value.get("t") == "MetaString":
        return [{"t": "Para", "c": [{"t": "Str", "c": value["c"]}]}]
    return []


def _leftovers(meta: dict, others: list) -> list:
    """The metadata no file of the project takes, a paragraph each, labelled with its style."""
    out = []
    for entry in others:
        out += _labelled("Author", _as_blocks(entry))
    for key in sorted(meta):
        out += _labelled(key.capitalize(), _as_blocks(meta[key]))
    return out


def _labelled(label: str, blocks: list) -> list:
    if not blocks:
        return []
    first = blocks[0]
    if first["t"] in ("Para", "Plain"):
        inlines = [{"t": "Str", "c": f"{label}:"}, _SPACE, *first["c"]]
        return [{"t": "Para", "c": inlines}, *blocks[1:]]
    return [{"t": "Para", "c": [{"t": "Str", "c": f"{label}:"}]}, *blocks]


def _heading(text: str) -> dict:
    words = text.split()
    inlines: list = []
    for word in words:
        inlines += [_SPACE, {"t": "Str", "c": word}] if inlines else [{"t": "Str", "c": word}]
    return {"t": "Header", "c": [1, [text.lower(), [], []], inlines]}


def _title_page(blocks: list) -> tuple[list, list, str]:
    """The blocks set aside, the blocks of the text, and what was done, in words."""
    first = next((at for at, block in enumerate(blocks) if block["t"] == "Header"), None)
    if first is None:
        return [], blocks, (
            "no paragraph is in a heading style, so nothing was set aside as the title page; "
            "a section whose heading is only bold text is not a section to any gate")
    if first == 0:
        return [], blocks, "the document opens on a heading, so nothing was set aside"
    before = blocks[:first]
    words = _words(before)
    if words > TITLE_PAGE_WORDS:
        return [], blocks, (
            f"the {words} words before the first heading are more than a title page holds "
            f"({TITLE_PAGE_WORDS}), so they were left in the text; set the title page "
            "aside in a comment by hand")
    return before, blocks[first:], (
        f"the {words} words before the first heading were set aside in a comment at the top "
        "of main.md, which no gate reads; move into the text what belongs to the paper")


def _tables(blocks: list) -> tuple[int, list[tuple[str, dict]]]:
    """Rewrite each table of the text as a pipe table where it can be one, in place, and
    leave every table's widths to its cells; the number rewritten, and each table left as it
    came, with why."""
    done = 0
    left: list[tuple[str, dict]] = []
    for number, table in enumerate(_tables_in(blocks), start=1):
        why = _flatten(table)
        table["c"][2] = [[spec[0], {"t": "ColWidthDefault"}] for spec in table["c"][2]]
        if why is None:
            done += 1
        else:
            first = " ".join(text_of(table["c"][3:5]).split())[:40]
            left.append((f'table {number} ("{first}"): {why}', table))
    return done, left


def _form(markdown: str) -> str:
    """What kind of table pandoc wrote."""
    start = markdown.lstrip()
    if start.startswith("+"):
        return "written as a grid table"
    if start.startswith("<"):
        return "written as raw HTML"
    return "written as pandoc writes it"


def _tables_in(node: object):
    """Each table of the text, outermost only: one inside a cell is part of its table."""
    if isinstance(node, dict):
        if node.get("t") == "Table":
            yield node
            return
        yield from _tables_in(node.get("c"))
    elif isinstance(node, list):
        for item in node:
            yield from _tables_in(item)


def _flatten(table: dict) -> str | None:
    """Make `table` one pipe tables can write, in place; None where it was made one, or what
    a cell holds that a pipe table cannot."""
    _attr, _caption, specs, head, bodies, foot = table["c"]
    rows = [*head[1]]
    for body in bodies:
        rows += [*body[2], *body[3]]
    rows += foot[1]
    width = len(specs)
    grid = _grid(rows, width)
    if isinstance(grid, str):
        return grid
    made = [[_NO_ATTR, cells] for cells in grid]
    heads = 1 if head[1] else 0
    table["c"][3] = [head[0], made[:heads]]
    table["c"][4] = [[_NO_ATTR, 0, [], made[heads:]]]
    table["c"][5] = [foot[0], []]
    return None


def _grid(rows: list, width: int) -> list | str:
    """The rows as a grid of `width` cells of one line each, a merged cell's text in its first
    row and column; or what a cell holds that cannot be one line."""
    grid: list[list] = [[None] * width for _ in rows]
    for at, row in enumerate(rows):
        column = 0
        for cell in row[1]:
            while column < width and grid[at][column] is not None:
                column += 1
            if column >= width:
                return "a row with more cells than the table has columns"
            _attr, align, down, across, content = cell
            inlines = _one_line(content)
            if isinstance(inlines, str):
                return f"{inlines} in a cell"
            for below in range(at, min(at + down, len(rows))):
                for right in range(column, min(column + across, width)):
                    grid[below][right] = _cell(align, [] if (below, right) != (at, column)
                                               else inlines)  # fmt: skip
            column += across
    return [[cell or _cell({"t": "AlignDefault"}, []) for cell in row] for row in grid]


def _cell(align: dict, inlines: list) -> list:
    return [_NO_ATTR, align, 1, 1, [{"t": "Plain", "c": inlines}] if inlines else []]


def _one_line(blocks: list) -> list | str:
    """A cell's blocks as one line of text, or the kind of block that cannot be one."""
    out: list = []
    for block in blocks:
        kind = block["t"]
        if kind not in _JOINED:
            return _KIND.get(kind, f"a {kind}")
        if kind in ("Para", "Plain"):
            part = block["c"]
        elif kind == "Header":
            part = block["c"][2]
        elif kind == "LineBlock":
            part = [inline for line in block["c"] for inline in [_SPACE, *line]]
        else:
            part = _one_line(block["c"] if kind == "BlockQuote" else block["c"][1])
            if isinstance(part, str):
                return part
        part = _unbroken(part)
        if out and part:
            out.append(_SPACE)
        out += part
    while out and out[0]["t"] == "Space":
        out.pop(0)
    while out and out[-1]["t"] == "Space":
        out.pop()
    return out


def _unbroken(inlines: list) -> list:
    """The inlines with each line break a space, inside emphasis too but not inside a note,
    whose paragraphs are its own."""
    out = []
    for inline in inlines:
        kind = inline["t"]
        if kind in ("SoftBreak", "LineBreak"):
            out.append(_SPACE)
        elif kind in ("Emph", "Strong", "Underline", "Strikeout", "Superscript", "Subscript",
                      "SmallCaps"):  # fmt: skip
            out.append({"t": kind, "c": _unbroken(inline["c"])})
        elif kind in ("Span", "Link", "Quoted", "Cite"):
            head, inner, *rest = inline["c"]
            out.append({"t": kind, "c": [head, _unbroken(inner), *rest]})
        else:
            out.append(inline)
    return out


def what_was_done(docx: Path, converted: Converted) -> str:
    """What `init --from` made of the paper, for the author to read before anything else."""
    name = Path(docx).name
    lines = [f"from {name}:"]
    lines.append(f"  title: {converted.title!r}, from its Title paragraph" if converted.title
                 else "  title: none taken from a Title paragraph")  # fmt: skip
    if converted.title_noted:
        lines.append("    paper.yaml has it as plain text, and the Title paragraph is in the "
                     "comment too, with the notes, marks, links or pictures it holds")  # fmt: skip
    if converted.title_marks:
        lines.append(f"    the superscript {converted.title_marks!r} at its end was taken for "
                     "the mark of a note and left out of it; if it is part of the title, put "
                     "it back in paper.yaml and in main.md's header")  # fmt: skip
    if converted.authors:
        lines.append(f"  authors: {len(converted.authors)} named in Author paragraphs, in "
                     "authors.yaml; split each name into given and family")  # fmt: skip
    if converted.abstract:
        lines.append("  abstract: from its Abstract paragraphs, as the section # Abstract")
    lines.append(f"  title page: {converted.title_page}")
    lines.append(f"  headings: {converted.headings}")
    lines.append(f"  tables: {converted.tables} written as pipe tables")
    if converted.tables_left:
        lines.append("  tables left as pandoc writes them: check reads a grid table's rows, "
                     "but the audit does not read its cells; rewrite each as a pipe table, "
                     "or emit it from the analysis:")  # fmt: skip
        lines += [f"    {left}" for left in converted.tables_left]
    lines.append(f"  pictures: {len(converted.media)} in {MEDIA}/")
    return "\n".join(lines)


#: The authors file `init --from` writes where Word's Author paragraphs named people.
AUTHORS = """\
schema: manuscript-guard/authors/1

affiliations:
  - id: a1
    text: "Department, Institution, City, Country"

# Each name is as the paper's Author paragraphs give it. Split it into its given and family
# name: `init --from` does not guess which is which.
authors:
{entries}"""

_ENTRY = """\
  # {name}
  - given: ""
    family: ""
    affiliations: [a1]
    corresponding: {corresponding}
    equal_contribution: false
"""


def authors_yaml(names: tuple[str, ...]) -> str:
    """`authors.yaml` with an entry for each name, the name in a comment above it."""
    entries = "".join(
        _ENTRY.format(name=name, corresponding="true" if at == 0 else "false")
        for at, name in enumerate(names)
    )
    return AUTHORS.format(entries=entries)


def init_from_word(root: Path, docx: Path, title: str | None = None,
                   english: str | None = None) -> tuple[list[Path], Converted]:  # fmt: skip
    """Make a project at `root` whose manuscript is the Word paper `docx`. `init` writes over
    nothing, so nothing is made where the paper cannot be read, where `root` already has a
    manuscript, where a picture cannot be written, or where `paper.yaml` or `authors.yaml`
    is there and the paper's title or names would go into neither. A file that is there and
    that nothing from the paper goes into is kept, as plain `init` keeps it. `english` is
    the English `paper.yaml` declares, as for plain `init`."""
    from manuscript_guard.gates.numbers import source_files
    from manuscript_guard.scaffold import UNTITLED, init_project

    root = Path(root).resolve()
    manuscript = root / "manuscript"
    there = source_files(manuscript) + source_files(manuscript, glob="*.tex")
    if there:
        raise ContractError(f"{there[0]} is already there, and init --from writes the paper as "
                            "manuscript/main.md over nothing; nothing was made")  # fmt: skip
    converted = convert(docx, titled=title is not None)
    if converted.title is not None and (root / "paper.yaml").exists():
        raise ContractError("paper.yaml is already there, and init keeps it, so the Word "
                            "paper's title would be written nowhere; move it aside, or give "
                            "--title to keep paper.yaml as it is; nothing was made")  # fmt: skip
    if converted.authors and (root / "authors.yaml").exists():
        named = len(converted.authors)
        raise ContractError(f"authors.yaml is already there, and init keeps it, so the "
                            f"{'name' if named == 1 else f'{named} names'} of the Word paper's "
                            "Author paragraphs would be written nowhere; move it aside; "
                            "nothing was made")  # fmt: skip
    why = _in_the_way(root, [name for name, _ in converted.media])
    if why is not None:
        raise ContractError(f"{why}, and init --from writes over nothing; nothing was made")
    created = init_project(
        root, title if title is not None else converted.title or UNTITLED, text=converted.text,
        authors=authors_yaml(converted.authors) if converted.authors else None,
        english=english,
    )  # fmt: skip
    for name, data in converted.media:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as handle:
            handle.write(data)
        created.append(path)
    return created, converted


def _in_the_way(root: Path, names: list[str]) -> str | None:
    """Why the pictures cannot all be written, asked before anything is made: a file where
    the project or a folder of a picture goes, something already at a picture's path, or two
    pictures whose paths differ only by case, which Windows and macOS take for one file."""
    folders = {"/".join(steps[:depth]).casefold(): "/".join(steps[:depth])
               for steps in (name.split("/") for name in names)
               for depth in range(1, len(steps))}  # fmt: skip
    files: dict[str, str] = {}
    for name in names:
        key = name.casefold()
        if key in files:
            return (f"two pictures of the Word paper, {files[key]} and {name}, differ only by "
                    "case, which Windows and macOS take for one file")  # fmt: skip
        if key in folders:
            return f"a picture of the Word paper, {name}, would be the folder {folders[key]}"
        files[key] = name
        steps = name.split("/")[:-1]
        for depth in range(len(steps) + 1):
            folder = root.joinpath(*steps[:depth])
            if folder.exists() and not folder.is_dir():
                return f"{folder} is a file where init --from puts a folder"
        if (root / name).exists() or (root / name).is_symlink():
            return f"{root / name} is already there"
    if root.exists() and not root.is_dir():
        return f"{root} is a file where init --from puts the project"
    return None
