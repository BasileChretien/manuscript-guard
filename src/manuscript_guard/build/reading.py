"""How pandoc reads the document the build is about to make, against how the gates read it.

The gates read the Markdown sources with a model of pandoc's reader, and every shape that
model got wrong was found by a review, one round at a time: a YAML block behind a `<div>`,
a list marker or a TeX command put another title on the title page, and a title
continuing a paragraph over `===` was a Methods heading to the gates and text to pandoc.
Five rounds of refusals each found more. So the build asks pandoc itself before it writes
the document: the metadata of the whole text must be the metadata of the build's header
alone, and the headings pandoc makes must be the headings the gates read. Most shapes
nobody has listed are caught here too, because nothing here lists shapes.

The gates read each source as it is on disk, placeholders and all, and the build reads the
same file with its values put in; each heading the gates read is paired with the one at
the same index in the built text, and a file whose headings change in number or level when
its values go in is a misreading of its own. Titles are compared as built, in pandoc's
words: each is read by
pandoc as a numbered paragraph of its own, so `HbA~1c~`, `$\\beta_{1}$` or `&amp;` split
into words as pandoc splits them. A title pandoc makes no paragraph of, block HTML in it,
is compared in its own words: giving up on it gave up on every heading. Raw markup and
footnotes print no words in a heading, and a heading in a quotation, a note or a figure is
left out on both sides: the gates read none there, by design (see
`test_a_quoted_heading_is_deliberately_not_a_section`). A heading in a list, a definition
or a table is the document's, and matches none the gates read, since they read none there.
It takes three runs of pandoc's reader a document, one of them on the header alone and
kept for the next document with the same header.
"""

from __future__ import annotations

import json
import re
import secrets
import subprocess
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from manuscript_guard.text.sections import heading_index, scannable

# Containers whose headings are quoted or set apart, not the document's own.
_NESTED = frozenset({"BlockQuote", "Note", "Figure"})
# Containers whose headings are the document's, and which the gates never read as one: a
# heading there matches none of theirs. Matched by its title, it stood in for a heading the
# gates misread elsewhere, and the claim between passed under the wrong one.
_LISTED = frozenset({"BulletList", "OrderedList", "DefinitionList", "Table"})
# Inlines that print no words: raw markup, an HTML comment among them, and a footnote.
_SILENT = frozenset({"RawInline", "Note"})
# Inlines read whole, and not inside.
_PRINTED = frozenset({"Str", "Code", "Math", "Space", "SoftBreak", "LineBreak"}) | _SILENT
_WORDS = re.compile(r"[^\W_]+")
# Link reference and footnote definitions, their text on the lines after included, and
# example list items, which a title may refer to.
_DEFINITION = re.compile(
    r"^[ ]{0,3}\[[^\]\n]+\]:.*(?:\n[ \t]+\S.*)*|^\(@[\w-]+\)[ \t].*", re.MULTILINE
)


@dataclass(frozen=True)
class _Read:
    """A heading the gates read: where, its level, its title as built, and its words as
    pandoc reads them, joined by spaces."""

    where: str
    level: int
    title: str
    words: str


def _json(markdown: str, pandoc: str, cwd: Path | None) -> dict | None:
    """Pandoc's reading of `markdown`, or None when pandoc cannot read it at all, which
    the build's own run of pandoc then reports."""
    finished = subprocess.run(
        [pandoc, "-f", "markdown", "-t", "json"],
        input=markdown.encode("utf-8"),
        capture_output=True,
        cwd=cwd,
    )
    if finished.returncode != 0:
        return None
    return json.loads(finished.stdout)


@lru_cache(maxsize=16)
def _header_meta(header: str, pandoc: str) -> str | None:
    """The metadata of the build's header read alone, as JSON text so that nothing can
    change the copy kept. It was read in one run with the titles and the definitions they
    refer to, and a footnote's definition holding a YAML block set a title there too."""
    read = _json(header, pandoc, None)
    return None if read is None else json.dumps(read["meta"], sort_keys=True)


def _nodes(tree, into: Callable[[dict], bool]) -> Iterator[dict]:
    """Every element of pandoc's reading in document order, read inside only where `into`
    says so. Without recursion: six hundred nested divs overflowed the stack."""
    stack = [tree]
    while stack:
        item = stack.pop()
        if isinstance(item, list):
            stack.extend(reversed(item))
        elif isinstance(item, dict):
            yield item
            if into(item):
                stack.append(item.get("c"))


def _plain(node) -> str:
    """The text of inlines as they print: `Str`, the text of code and maths, and a space
    for a space. Attributes and link targets are strings inside lists, and print nothing."""
    printed = []
    for item in _nodes(node, lambda item: item.get("t") not in _PRINTED):
        kind, content = item.get("t"), item.get("c")
        if kind == "Str":
            printed.append(content)
        elif kind in ("Code", "Math"):
            printed.append(f" {content[1]} ")
        elif kind in _PRINTED:
            printed.append(" ")
    return "".join(printed)


def _words(text: str) -> str:
    return " ".join(_WORDS.findall(text.lower()))


@dataclass(frozen=True)
class _Printed:
    """A heading pandoc makes: its level, its words, its text for a message, and whether it
    stands in a list, a definition or a table, where the gates read no heading."""

    level: int
    words: str
    text: str
    listed: bool


def _headers(blocks: list) -> list[_Printed]:
    """Each heading pandoc makes, outside quotations, notes and figures. Walked with a
    stack, not by recursion, carrying whether a list, a definition or a table holds it."""
    found: list[_Printed] = []
    stack: list[tuple[object, bool]] = [(blocks, False)]
    while stack:
        item, listed = stack.pop()
        if isinstance(item, list):
            stack.extend((child, listed) for child in reversed(item))
        elif isinstance(item, dict):
            kind = item.get("t")
            if kind in _NESTED:
                continue
            if kind == "Header":
                level, _attributes, inlines = item["c"]
                text = _plain(inlines)
                found.append(_Printed(level, _words(text), " ".join(text.split()), listed))
                continue
            stack.append((item.get("c"), listed or kind in _LISTED))
    return found


def _changed(name: str, written: str, written_at: list, built_at: list) -> str | None:
    """How the headings the gates read in a file as written differ from those of its text
    with the values put in, or None when they pair one to one at the same levels. A value
    is data and holds no heading; one that changed the headings would have the gates judge
    other sections than the ones the build prints."""
    at = next(
        (
            k
            for k, (w, b) in enumerate(zip(written_at, built_at, strict=False))
            if w.level != b.level
        ),
        min(len(written_at), len(built_at)),
    )
    if at == len(written_at) == len(built_at):
        return None
    before = (
        f"the level-{written_at[at].level} heading {written_at[at].title!r} at "
        f"{name}:{written.count(chr(10), 0, written_at[at].start) + 1}"
        if at < len(written_at)
        else "no heading"
    )
    after = (
        f"a level-{built_at[at].level} heading {built_at[at].title!r}"
        if at < len(built_at)
        else "none"
    )
    return (
        f"{name} with its values put in as other headings than the gates read in it: "
        f"{before} as written, and {after} as built"
    )


def _titles(
    sources: list[tuple[str, str]], built: list[str], lead: str
) -> tuple[list[tuple[str, int, str]], str] | str:
    """Every heading the gates read, where and at what level, with its title as built, and
    a document reading each title as a paragraph of its own behind `lead` and its number,
    the built definitions after them. A phrase for `misreading` instead when a file's
    headings change with its values put in."""
    found: list[tuple[str, int, str]] = []
    paragraphs: list[str] = []
    definitions: list[str] = []
    for (name, written), made in zip(sources, built, strict=True):
        # From the text pandoc reads, not from code or a comment: a commented-out footnote
        # holding YAML pandoc cannot read, copied, made the titles' own run fail.
        definitions += (
            made[match.start() : match.end()] for match in _DEFINITION.finditer(scannable(made))
        )
        written_at, built_at = heading_index(written), heading_index(made)
        changed = _changed(name, written, written_at, built_at)
        if changed is not None:
            return changed
        for heading, shown in zip(written_at, built_at, strict=True):
            where = f"{name}:{written.count(chr(10), 0, heading.start) + 1}"
            paragraphs.append(f"{lead}{len(found)} {shown.title}")
            found.append((where, heading.level, shown.title))
    return found, "\n\n".join([*paragraphs, *definitions])


def _numbered(blocks: list, lead: str) -> dict[int, str]:
    """The text of each paragraph that opens with `lead` and a number, by its number. A
    number that comes back twice is dropped, and its title compared in its own words."""
    pattern = re.compile(rf"{lead}(\d+)")

    def number_of(node: dict) -> int | None:
        content = node.get("c")
        if node.get("t") not in ("Para", "Plain") or not content:
            return None
        if content[0].get("t") != "Str":
            return None
        numbered = pattern.fullmatch(content[0]["c"])
        return None if numbered is None else int(numbered.group(1))

    found: dict[int, str] = {}
    twice: set[int] = set()
    for node in _nodes(blocks, lambda node: number_of(node) is None):
        number = number_of(node)
        if number is not None:
            if number in found:
                twice.add(number)
            found[number] = _plain(node["c"][1:])
    return {number: text for number, text in found.items() if number not in twice}


def _first_difference(read: list[_Read], printed: list[_Printed]) -> str | None:
    """The first heading, in document order, that one side reads and the other does not,
    the two lists aligned so that one extra heading names itself and not the next pair."""
    rows, columns = len(read), len(printed)

    def same(i: int, j: int) -> bool:
        return (
            not printed[j].listed
            and read[i].level == printed[j].level
            and read[i].words == printed[j].words
        )

    common = [[0] * (columns + 1) for _ in range(rows + 1)]
    for i in range(rows - 1, -1, -1):
        for j in range(columns - 1, -1, -1):
            common[i][j] = (
                common[i + 1][j + 1] + 1
                if same(i, j)
                else max(common[i + 1][j], common[i][j + 1])
            )

    def only_read(i: int) -> str:
        return (
            f"as text the level-{read[i].level} heading {read[i].title!r} at "
            f"{read[i].where}, which the gates read as a heading"
        )

    def only_printed(j: int) -> str:
        where = " in a list, a definition or a table," if printed[j].listed else ""
        return (
            f"a level-{printed[j].level} heading {printed[j].text!r}{where} that the gates "
            "read as text"
        )

    i = j = 0
    while i < rows and j < columns:
        if same(i, j):
            i, j = i + 1, j + 1
            continue
        if common[i + 1][j + 1] == common[i][j] and not printed[j].listed:
            return (
                f"the heading {printed[j].text!r} (level {printed[j].level}) where the gates "
                f"read {read[i].title!r} (level {read[i].level}) at {read[i].where}"
            )
        return only_read(i) if common[i + 1][j] >= common[i][j + 1] else only_printed(j)
    if i < rows:
        return only_read(i)
    return only_printed(j) if j < columns else None


def misreading(
    source: str,
    header: str,
    sources: list[tuple[str, str]],
    pandoc: str,
    cwd: Path,
    *,
    built: list[str] | None = None,
) -> str | None:
    """What pandoc reads in `source`, the text the build hands it, otherwise than the gates
    read `sources`, each file's name and text as it is on disk, and anything the build adds,
    in order: a phrase to follow "pandoc reads". `built` is each of those texts as the
    build puts it in `source`, values in; without it, the sources are taken as built. None
    when they agree, and when pandoc cannot read `source` at all, which the build's own run
    of pandoc then reports."""
    try:
        return _compared(source, header, sources, pandoc, cwd, built)
    except RecursionError:
        # Python's JSON reader recurses, and two thousand nested divs overflow it. Not
        # compared is not agreed: the build stops.
        return (
            "a document nested too deep for its reading to be compared with the gates'. "
            "Quotations, lists or divs nested hundreds deep do this"
        )


def _compared(
    source: str,
    header: str,
    sources: list[tuple[str, str]],
    pandoc: str,
    cwd: Path,
    built: list[str] | None,
) -> str | None:
    """`misreading`, which see."""
    # A lead nobody can type: a paragraph of the author's that opens with a fixed one came
    # back as a title's.
    lead = f"mgtitle{secrets.token_hex(8)}n"
    titled = _titles(sources, built if built is not None else [t for _, t in sources], lead)
    if isinstance(titled, str):
        return titled
    found, titles = titled
    whole = _json(source, pandoc, cwd)
    if whole is None:
        return None
    meta = _header_meta(header, pandoc)
    alone = _json(f"{titles}\n", pandoc, cwd) if found else {"blocks": []}
    if meta is None or alone is None:
        # The document reads, and what it is compared with does not: passed, the check was
        # off for every heading of a document holding a misread one.
        return (
            "the document, but not the build's header or the gates' titles set out on their "
            "own, so their reading cannot be compared with the gates'"
        )
    set_by_header = json.loads(meta)
    set_by_text = sorted(
        key
        for key in set(whole["meta"]) | set(set_by_header)
        if whole["meta"].get(key) != set_by_header.get(key)
    )
    if set_by_text:
        return (
            f"metadata in the text itself ({', '.join(set_by_text)}), which the gates never "
            "read and only the build's header, from paper.yaml, may set. A YAML block below "
            "the front matter does this; move what it holds into paper.yaml"
        )
    numbered = _numbered(alone["blocks"], lead)
    read = [
        _Read(
            where,
            level,
            title,
            _words(numbered[number]) if number in numbered else _words(title),
        )
        for number, (where, level, title) in enumerate(found)
    ]
    return _first_difference(read, _headers(whole["blocks"]))
