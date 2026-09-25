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

A listing is found by position, not by its lines: a numbered line is put first in each, in
the copy pandoc reads, and must come back first in a code block. Matched by its lines, a
listing the gates read inside a raw block passed for a copy of the same lines elsewhere.
Code pandoc makes that the gates read as prose, an indented listing say, is the safe side.

The gates read each source as it is on disk, placeholders and all. Their titles are read by
pandoc as well, in the same run as the header, so both sides are compared in pandoc's
words: `HbA~1c~`, `$\\beta_{1}$` or `&amp;` in a title split into words as pandoc splits
them. A placeholder stands for whatever its value prints as. Raw markup and footnotes print
no words in a heading, and quoted headings are left out on both sides: the gates read none,
by design (see `test_a_quoted_heading_is_deliberately_not_a_section`). Two runs of pandoc's
reader a document.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from manuscript_guard.text.fences import Fence, fenced_spans
from manuscript_guard.text.masking import front_matter_end
from manuscript_guard.text.placeholders import PLACEHOLDER
from manuscript_guard.text.sections import heading_index

# Containers whose headings are quoted or set apart, not the document's own.
_NESTED = frozenset({"BlockQuote", "Note", "Figure"})
# Inlines that print no words: raw markup, an HTML comment among them, and a footnote.
_SILENT = frozenset({"RawInline", "Note"})
_WORDS = re.compile(r"[^\W_]+")
# Written for a placeholder in a title, and matching whatever its value prints as.
_VALUE = "mgvalue"
# In front of each title read on its own, so that it is a paragraph whatever it starts with.
_LEAD = "mgtitle"
# Link reference and footnote definitions, which a title may refer to.
_DEFINITION = re.compile(r"^[ ]{0,3}\[[^\]\n]+\]:[ \t].*$", re.MULTILINE)
# Put first in each listing the gates read, numbered, in the copy pandoc reads: a listing is
# found where it stands, not by its lines, which a copy elsewhere has too.
_MARK = "mglisting"


@dataclass(frozen=True)
class _Read:
    """A heading the gates read: where, its level, its title as written, and its words
    as pandoc reads them, None for a placeholder's."""

    where: str
    level: int
    title: str
    words: tuple[str | None, ...]


def _json(markdown: str, pandoc: str, cwd: Path) -> dict | None:
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


def _plain(node) -> str:
    """The text of inlines as they print: `Str`, the text of code and maths, and a space
    for a space. Attributes and link targets are strings inside lists, and print nothing."""
    if isinstance(node, list):
        return "".join(_plain(item) for item in node)
    if not isinstance(node, dict):
        return ""
    kind, content = node.get("t"), node.get("c")
    if kind in _SILENT:
        return " "
    if kind == "Str":
        return content
    if kind in ("Space", "SoftBreak", "LineBreak"):
        return " "
    if kind in ("Code", "Math"):
        return f" {content[1]} "
    return _plain(content)


def _words(inlines) -> list[str]:
    return _WORDS.findall(_plain(inlines).lower())


def _headers(blocks: list) -> list[tuple[int, list[str], str]]:
    """Each heading pandoc makes, outside quotations, notes and figures: its level, its
    words, and its text for a message."""
    found: list[tuple[int, list[str], str]] = []

    def walk(node) -> None:
        if isinstance(node, dict):
            if node.get("t") in _NESTED:
                return
            if node.get("t") == "Header":
                level, _attributes, inlines = node["c"]
                found.append((level, _words(inlines), " ".join(_plain(inlines).split())))
                return
            walk(node.get("c"))
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(blocks)
    return found


def _titles(sources: list[tuple[str, str]]) -> tuple[list[tuple[str, int, str]], str]:
    """Every heading the gates read, where and at what level, and a document reading each
    title as a paragraph of its own, a placeholder written as `_VALUE`, with the sources'
    link and footnote definitions after them."""
    found: list[tuple[str, int, str]] = []
    paragraphs: list[str] = []
    definitions: list[str] = []
    for name, text in sources:
        definitions += _DEFINITION.findall(text)
        for heading in heading_index(text):
            where = f"{name}:{text.count(chr(10), 0, heading.start) + 1}"
            found.append((where, heading.level, heading.title))
            paragraphs.append(f"{_LEAD} {PLACEHOLDER.sub(f' {_VALUE} ', heading.title)}")
    return found, "\n\n".join([*paragraphs, *definitions])


def _lines(code: str) -> str:
    """A listing's lines without their indentation and blank lines, spaces run together."""
    return "\n".join(" ".join(line.split()) for line in code.split("\n") if line.strip())


def _fits_text(template: str, text: str) -> bool:
    """Does `text` read as `template`, each placeholder in it standing for any text? The
    parts between are found in order, left to right, so this is linear: joined by `.*?`
    into one pattern, six placeholder lines against a long comment ran past two minutes."""
    parts = PLACEHOLDER.split(template)[::3]
    if len(parts) == 1:
        return template == text
    first, last = parts[0], parts[-1]
    if len(text) < len(first) + len(last) or not (
        text.startswith(first) and text.endswith(last)
    ):
        return False
    at, end = len(first), len(text) - len(last)
    for part in parts[1:-1]:
        found = text.find(part, at, end)
        if found < 0:
            return False
        at = found + len(part)
    return True


def _marked(source: str) -> tuple[str, list[Fence]]:
    """`source` with a numbered line put first in each listing the gates read in it, and
    those listings."""
    fences = fenced_spans(source, front_matter_end(source))
    pieces: list[str] = []
    at = 0
    for number, fence in enumerate(fences):
        pieces += [source[at : fence.body_start], f"{_MARK}{number}\n"]
        at = fence.body_start
    pieces.append(source[at:])
    return "".join(pieces), fences


def _first_lines(blocks: list) -> dict[str, str]:
    """The first line of every code block and raw block pandoc makes, and which it is."""
    found: dict[str, str] = {}

    def walk(node) -> None:
        if isinstance(node, dict):
            if node.get("t") in ("CodeBlock", "RawBlock"):
                found[node["c"][1].split("\n", 1)[0]] = node["t"]
                return
            walk(node.get("c"))
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(blocks)
    return found


def _listing_misread(
    blocks: list, source: str, fences: list[Fence], sources: list[tuple[str, str]]
) -> str | None:
    """The first listing the gates read in `sources` that pandoc does not make where it
    stands: paired in order with the listings in `source`, the text the build hands pandoc,
    each of which must be a code block, or a raw block for `{=format}`, opening with its
    numbered line."""
    read = [
        (f"{name}:{text.count(chr(10), 0, fence.start) + 1}", fence, text)
        for name, text in sources
        for fence in fenced_spans(text, front_matter_end(text))
    ]
    made = _first_lines(blocks)
    for number, (where, fence, text) in enumerate(read):
        opener = text[fence.start : fence.body_start].strip()
        built = fences[number] if number < len(fences) else None
        if (
            built is None
            or not _fits_text(
                _lines(text[fence.body_start : fence.body_end]),
                _lines(source[built.body_start : built.body_end]),
            )
            or made.get(f"{_MARK}{number}") != ("RawBlock" if built.is_raw else "CodeBlock")
        ):
            return f"as something other than code the listing opened by {opener!r} at {where}"
    if len(fences) > len(read):
        extra = fences[len(read)]
        opener = source[extra.start : extra.body_start].strip()
        return f"a listing opened by {opener!r} that the gates did not read in the sources"
    return None


def _fits(template: tuple[str | None, ...], words: list[str]) -> bool:
    """Do `words` read as `template`, a placeholder standing for any run of words?"""
    reached = {0}
    for item in template:
        if item is None:
            reached = set(range(min(reached), len(words) + 1)) if reached else set()
        else:
            reached = {at + 1 for at in reached if at < len(words) and words[at] == item}
    return len(words) in reached


def _first_difference(read: list[_Read], printed: list[tuple[int, list[str], str]]) -> str | None:
    """The first heading, in document order, that one side reads and the other does not,
    the two lists aligned so that one extra heading names itself and not the next pair."""
    rows, columns = len(read), len(printed)

    def same(i: int, j: int) -> bool:
        return read[i].level == printed[j][0] and _fits(read[i].words, printed[j][1])

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
        if same(i, j) and common[i][j] == common[i + 1][j + 1] + 1:
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


def misreading(
    source: str, header: str, sources: list[tuple[str, str]], pandoc: str, cwd: Path
) -> str | None:
    """What pandoc reads in `source`, the text the build hands it, otherwise than the gates
    read `sources`, each file's name and text as it is on disk, and anything the build adds,
    in order: a phrase to follow "pandoc reads". None when they agree, and when pandoc
    cannot read `source`."""
    found, titles = _titles(sources)
    marked, fences = _marked(source)
    whole = _json(marked, pandoc, cwd)
    alone = _json(f"{header}\n{titles}\n", pandoc, cwd)
    if whole is None or alone is None:
        if alone is not None and _json(source, pandoc, cwd) is not None:
            # A line put first in a listing the gates read changed how the text reads, so
            # to pandoc the listing is something else.
            return "as something other than code a listing the gates read"
        return None
    set_by_text = sorted(
        key
        for key in set(whole["meta"]) | set(alone["meta"])
        if whole["meta"].get(key) != alone["meta"].get(key)
    )
    if set_by_text:
        return (
            f"metadata in the text itself ({', '.join(set_by_text)}), which the gates never "
            "read and only the build's header, from paper.yaml, may set. A YAML block below "
            "the front matter does this; move what it holds into paper.yaml"
        )
    paragraphs = [block for block in alone["blocks"] if block.get("t") == "Para"]
    if len(paragraphs) < len(found):
        return None  # a title pandoc could not read on its own; the build reads on
    read = [
        _Read(
            where,
            level,
            title,
            tuple(None if word == _VALUE else word for word in _words(para["c"])[1:]),
        )
        for (where, level, title), para in zip(found, paragraphs, strict=False)
    ]
    return _first_difference(read, _headers(whole["blocks"])) or _listing_misread(
        whole["blocks"], source, fences, sources
    )
