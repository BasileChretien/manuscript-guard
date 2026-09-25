"""How pandoc reads the document the build is about to make, against how the gates read it.

The gates read the Markdown sources with a model of pandoc's reader, and every shape that
model got wrong was found by a review, one round at a time: a YAML block behind a `<div>`,
a list marker or a TeX command put another title on the title page, and a title
continuing a paragraph over `===` was a Methods heading to the gates and text to pandoc.
Five rounds of refusals each found more. So the build asks pandoc itself, once, before it
writes the document: the metadata of the whole text must be the metadata of the build's
header alone, the headings pandoc makes must be the headings the gates read, and every
listing the gates mask must be code pandoc makes. A shape nobody has listed is caught here
too, because nothing here lists shapes.

The gates read each source as it is on disk, placeholders and all, so a placeholder in a
title or a listing matches whatever its value prints as. Quoted headings are left out on
both sides: the gates read none, by design (see
`test_a_quoted_heading_is_deliberately_not_a_section`). Code pandoc makes that the gates
read as prose, an indented listing say, is the safe side, and is let be.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections import Counter
from pathlib import Path

from manuscript_guard.text.fences import fenced_spans
from manuscript_guard.text.masking import front_matter_end
from manuscript_guard.text.placeholders import PLACEHOLDER
from manuscript_guard.text.sections import heading_index

# Containers whose headings are quoted or set apart, not the document's own.
_NESTED = frozenset({"BlockQuote", "Note", "Figure"})
_WORDS = re.compile(r"[^\W_]+")
# What a heading's source carries that pandoc prints nothing of: attributes and bookmarks,
# `{#id .class}` and `[]{#mg-p-…}`, and a link's or an image's target.
_ATTRIBUTES = re.compile(r"\{[^{}\n]*\}")
_TARGET = re.compile(r"\]\([^)\n]*\)")
_HOLE = "\x00"


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
    """The text of inlines as they print: `Str`, the text of code, maths and raw markup,
    and a space for a space. Attributes and link targets are strings inside lists, and
    print nothing."""
    if isinstance(node, list):
        return "".join(_plain(item) for item in node)
    if not isinstance(node, dict):
        return ""
    kind, content = node.get("t"), node.get("c")
    if kind == "Str":
        return content
    if kind in ("Space", "SoftBreak", "LineBreak"):
        return " "
    if kind in ("Code", "Math", "RawInline"):
        return f" {content[1]} "
    return _plain(content)


def _headers(blocks: list) -> list[tuple[int, str]]:
    """Each heading pandoc makes, its level and text, outside quotations, notes and figures."""
    found: list[tuple[int, str]] = []

    def walk(node) -> None:
        if isinstance(node, dict):
            if node.get("t") in _NESTED:
                return
            if node.get("t") == "Header":
                level, _attributes, inlines = node["c"]
                found.append((level, _plain(inlines).strip()))
                return
            walk(node.get("c"))
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(blocks)
    return found


def _lines(code: str) -> str:
    """A listing's lines without their indentation, which pandoc takes off in a list item,
    and without blank lines, spaces run together."""
    return "\n".join(" ".join(line.split()) for line in code.split("\n") if line.strip())


def _code(blocks: list) -> Counter[str]:
    """The lines of every code block and raw block pandoc makes, anywhere in the document."""
    found: Counter[str] = Counter()

    def walk(node) -> None:
        if isinstance(node, dict):
            if node.get("t") in ("CodeBlock", "RawBlock"):
                found[_lines(node["c"][1])] += 1
                return
            walk(node.get("c"))
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(blocks)
    return found


def _listing_misread(blocks: list, sources: list[str]) -> str | None:
    """The first listing the gates mask in `sources` that is no code pandoc makes."""
    made = _code(blocks)
    for text in sources:
        for fence in fenced_spans(text, front_matter_end(text)):
            body = _lines(text[fence.body_start : fence.body_end])
            if PLACEHOLDER.search(body):
                pattern = re.compile(
                    ".*?".join(re.escape(part) for part in PLACEHOLDER.split(body)[::3]),
                    re.DOTALL,
                )
                body = next((code for code in made if made[code] and pattern.fullmatch(code)), body)
            if made[body]:
                made[body] -= 1
                continue
            opener = text[fence.start : fence.body_start].strip()
            return f"as text the listing the gates read as code, opened by {opener!r}"
    return None


def _template(title: str) -> list[str | None]:
    """A title's words as the gates read it, None for each placeholder."""
    holed = PLACEHOLDER.sub(_HOLE, title)
    holed = _TARGET.sub("]", _ATTRIBUTES.sub(" ", holed))
    template: list[str | None] = []
    for index, part in enumerate(holed.split(_HOLE)):
        if index:
            template.append(None)
        template.extend(_WORDS.findall(part.lower()))
    return template


def _fits(template: list[str | None], words: list[str]) -> bool:
    """Do `words` read as `template`, a placeholder standing for any run of words?"""
    reached = {0}
    for item in template:
        if item is None:
            reached = set(range(min(reached), len(words) + 1)) if reached else set()
        else:
            reached = {at + 1 for at in reached if at < len(words) and words[at] == item}
    return len(words) in reached


def misreading(
    source: str, header: str, sources: list[str], pandoc: str, cwd: Path
) -> str | None:
    """What pandoc reads in `source`, the text the build hands it, otherwise than the gates
    read `sources`, each file as it is on disk and anything the build adds, in order: a
    phrase to follow "pandoc reads". None when they agree, and when pandoc cannot read
    `source`."""
    whole = _json(source, pandoc, cwd)
    alone = _json(header, pandoc, cwd)
    if whole is None or alone is None:
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
    printed = _headers(whole["blocks"])
    read = [(found.level, found.title) for text in sources for found in heading_index(text)]
    # The shorter list first; what is left over in either is the difference named below.
    for (level, text), (read_level, title) in zip(printed, read, strict=False):
        if level != read_level or not _fits(_template(title), _WORDS.findall(text.lower())):
            return (
                f"the heading {text!r} (level {level}) where the gates read {title!r} "
                f"(level {read_level})"
            )
    if len(printed) > len(read):
        level, text = printed[len(read)]
        return f"a level-{level} heading {text!r} the gates read as text"
    if len(read) > len(printed):
        level, title = read[len(printed)]
        return f"as text the level-{level} heading {title!r} the gates read"
    return _listing_misread(whole["blocks"], sources)
