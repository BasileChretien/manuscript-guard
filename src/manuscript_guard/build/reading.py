"""How pandoc reads the document the build is about to make, against how the gates read it.

The gates read the Markdown sources with a model of pandoc's reader, and every shape that
model got wrong was found by a review, one round at a time: a YAML block behind a `<div>`,
a list marker or a TeX command put another title on the title page, and a title
continuing a paragraph over `===` was a Methods heading to the gates and text to pandoc.
Five rounds of refusals each found more. So the build asks pandoc itself before it writes
the document: the metadata of the whole text must be the metadata of the build's header
alone, the headings pandoc makes must be the headings the gates read, and every listing the
gates read must be code pandoc makes where it stands. Most shapes nobody has listed are
caught here too, because nothing here lists shapes.

A listing is found by position, not by its lines: a line of its own is put first in each,
in the copy pandoc reads, and must come back once, first in a code block. Matched by its
lines, a listing the gates read inside a raw block passed for a copy of the same lines
elsewhere, and with a fixed line, for a copy of that line: the line is made new each
build. Code pandoc makes that the gates read as prose, an indented listing, is let be.

The gates read each source as it is on disk, placeholders and all, and the build reads the
same file with its values put in; each heading the gates read is paired with the one at
its place in the built text, and a file whose headings change when its values go in is a
misreading of its own. Titles are compared as built, in pandoc's words: each is read by
pandoc as a numbered paragraph of its own, so `HbA~1c~`, `$\\beta_{1}$` or `&amp;` split
into words as pandoc splits them. A title pandoc makes no paragraph of, block HTML in it,
is compared in its own words: giving up on it gave up on every heading. Raw markup and
footnotes print no words in a heading, and a heading in a quotation, a note or a figure is
left out on both sides: the gates read none there, by design (see
`test_a_quoted_heading_is_deliberately_not_a_section`). A heading in a list, a definition
or a table is the document's, and the gates reading its section as text is a misreading.
It takes three runs of pandoc's reader a document, one of them on the header alone and
kept for the next document with the same header.
"""

from __future__ import annotations

import json
import re
import secrets
import subprocess
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from manuscript_guard.text.fences import Fence, fenced_spans
from manuscript_guard.text.masking import front_matter_end
from manuscript_guard.text.sections import heading_index

# Containers whose headings are quoted or set apart, not the document's own.
_NESTED = frozenset({"BlockQuote", "Note", "Figure"})
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


def _headers(blocks: list) -> list[tuple[int, str, str]]:
    """Each heading pandoc makes, outside quotations, notes and figures: its level, its
    words, and its text for a message."""
    found: list[tuple[int, str, str]] = []
    for node in _nodes(blocks, lambda node: node.get("t") not in _NESTED | {"Header"}):
        if node.get("t") == "Header":
            level, _attributes, inlines = node["c"]
            text = _plain(inlines)
            found.append((level, _words(text), " ".join(text.split())))
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
        definitions += (match.group() for match in _DEFINITION.finditer(made))
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


def _first_difference(read: list[_Read], printed: list[tuple[int, str, str]]) -> str | None:
    """The first heading, in document order, that one side reads and the other does not,
    the two lists aligned so that one extra heading names itself and not the next pair."""
    rows, columns = len(read), len(printed)

    def same(i: int, j: int) -> bool:
        return read[i].level == printed[j][0] and read[i].words == printed[j][1]

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
        level, _words_of, text = printed[j]
        return f"a level-{level} heading {text!r} that the gates read as text"

    i = j = 0
    while i < rows and j < columns:
        if same(i, j):
            i, j = i + 1, j + 1
            continue
        if common[i + 1][j + 1] == common[i][j]:
            level, _words_of, text = printed[j]
            return (
                f"the heading {text!r} (level {level}) where the gates read "
                f"{read[i].title!r} (level {read[i].level}) at {read[i].where}"
            )
        return only_read(i) if common[i + 1][j] >= common[i][j + 1] else only_printed(j)
    if i < rows:
        return only_read(i)
    return only_printed(j) if j < columns else None


def _lines(code: str) -> str:
    """A listing's lines without their indentation and blank lines, spaces run together."""
    return "\n".join(" ".join(line.split()) for line in code.split("\n") if line.strip())


def _marked(source: str, mark: str) -> tuple[str, list[Fence]]:
    """`source` with `mark` and a number put first in each listing the gates read in it,
    and those listings."""
    fences = fenced_spans(source, front_matter_end(source))
    pieces: list[str] = []
    at = 0
    for number, fence in enumerate(fences):
        pieces += [source[at : fence.body_start], f"{mark}{number}\n"]
        at = fence.body_start
    pieces.append(source[at:])
    return "".join(pieces), fences


def _first_lines(blocks: list) -> Counter[tuple[str, str]]:
    """The first line of every code block and raw block pandoc makes, with which it is,
    counted."""
    found: Counter[tuple[str, str]] = Counter()
    for node in _nodes(blocks, lambda node: node.get("t") not in ("CodeBlock", "RawBlock")):
        if node.get("t") in ("CodeBlock", "RawBlock"):
            found[(node["c"][1].split("\n", 1)[0], node["t"])] += 1
    return found


def _listing_misread(
    blocks: list,
    source: str,
    fences: list[Fence],
    sources: list[tuple[str, str]],
    built: list[str],
    mark: str,
) -> str | None:
    """The first listing the gates read in `sources` that pandoc does not make where it
    stands. Each is paired with the one at its place in the same file as built, values in,
    and in order with the listings in `source`, the text the build hands pandoc, each of
    which must hold the same lines and be one code block, or raw block for `{=format}`,
    opening with its marked line."""
    made = _first_lines(blocks)
    number = 0
    for (name, text), shown in zip(sources, built, strict=True):
        written = fenced_spans(text, front_matter_end(text))
        own = fenced_spans(shown, front_matter_end(shown))
        if len(written) != len(own):
            return (
                f"{name} with its values put in as other listings than the gates read in it: "
                f"{len(written)} as written, and {len(own)} as built"
            )
        for fence, as_built in zip(written, own, strict=True):
            at = fences[number] if number < len(fences) else None
            kind = "RawBlock" if at is not None and at.is_raw else "CodeBlock"
            if (
                at is None
                or _lines(shown[as_built.body_start : as_built.body_end])
                != _lines(source[at.body_start : at.body_end])
                or made[(f"{mark}{number}", kind)] != 1
            ):
                where = f"{name}:{text.count(chr(10), 0, fence.start) + 1}"
                opener = text[fence.start : fence.body_start].strip()
                return f"as something other than code the listing opened by {opener!r} at {where}"
            number += 1
    if len(fences) > number:
        extra = fences[number]
        opener = source[extra.start : extra.body_start].strip()
        return f"a listing opened by {opener!r} that the gates did not read in the sources"
    return None


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
    made = built if built is not None else [text for _name, text in sources]
    # Leads nobody can type: a paragraph of the author's that opens with a fixed one came
    # back as a title's, and a listing opening with one passed for another listing.
    lead = f"mgtitle{secrets.token_hex(8)}n"
    titled = _titles(sources, made, lead)
    if isinstance(titled, str):
        return titled
    found, titles = titled
    mark = f"mglisting{secrets.token_hex(8)}n"
    marked, fences = _marked(source, mark)
    whole = _json(marked, pandoc, cwd)
    meta = _header_meta(header, pandoc)
    alone = _json(f"{titles}\n", pandoc, cwd) if found else {"blocks": []}
    if meta is None or alone is None:
        return None
    if whole is None:
        if _json(source, pandoc, cwd) is not None:
            # A line put first in a listing the gates read changed how the text reads, so
            # to pandoc the listing is something else.
            return "as something other than code a listing the gates read"
        return None
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
    return _first_difference(read, _headers(whole["blocks"])) or _listing_misread(
        whole["blocks"], source, fences, sources, made, mark
    )
