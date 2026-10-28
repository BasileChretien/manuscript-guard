"""The boxes a journal prints beside its abstract, read as the paper writes them.

A journal may ask for highlights, key points, a research-in-context panel or a plain-language
summary: a short text of its own, under a heading of its own, often of a set number of items
of a set length. The profile names each box it asks for (`boxes:`), with the heading it goes
under, a regular expression, and the LaTeX environment that writes it. This module finds each
box in a manuscript file and gives what it prints: each item, and the whole text.

- In Markdown, a box is a section whose heading the box's `heading` names, with its
  subsections. Its items are its list's items; where it has no list, its paragraphs.
- In LaTeX, a box is the box's environment (`\\begin{highlights}`), or a section whose heading
  names it, as in Markdown. Its items are its `\\item`s; where it has none, its paragraphs.

What is printed is read: HTML comments, listings and LaTeX comments are passed over, a binding
is its value's display, and Markdown's marks and LaTeX's commands are taken off. G4 holds each
box to the profile's limits (`gates/journal_boxes.py`), and G8 reads a box's numbers as a
summary's (`gates/reported.py`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from manuscript_guard.text.blocks import scannable
from manuscript_guard.text.masking import front_matter_end
from manuscript_guard.text.placeholders import parse
from manuscript_guard.text.section_names import plain
from manuscript_guard.text.sections import count_words, split_sections

#: A line that opens an item of a Markdown list, and the item's text after its mark.
_ITEM = re.compile(r"^ {0,3}(?:[-*+]|\d{1,9}[.)])(?:[ \t]+(.*)|[ \t]*)$")
#: A line of a Markdown heading, which is no part of an item or a paragraph.
_HEADING_LINE = re.compile(r"^ {0,3}#{1,6}(?:[ \t]|$)|^ {0,3}(?:=+|-+)[ \t]*$")
#: A Markdown link or image, printed as its text.
_LINK = re.compile(r"!?\[([^\]\n]*)\]\([^)\n]*\)")
#: Markdown's emphasis and code marks, at the edge of a word.
_MARKS = re.compile(r"(?<!\w)[*_]+|[*_]+(?!\w)|`+")
_SPACE = re.compile(r"\s+")
#: A LaTeX list's item, and the end of the list that holds it.
_LATEX_ITEM = re.compile(r"\\item(?![A-Za-z@])")
_LATEX_LIST_END = re.compile(r"\\end\s*\{(?:itemize|enumerate|description)\*?\}")
_NUL = "\x00"


@dataclass(frozen=True)
class BoxRule:
    """A box the journal's profile asks for: its id, the heading it goes under and the LaTeX
    environment that writes it."""

    id: str
    heading: re.Pattern[str]
    environment: str

    def names(self, title: str) -> bool:
        """Whether a heading titled `title` is this box's, read as printed: its number off
        and its marks (`plain`), those of an emphasis after a number too ("1. **Highlights**",
        which `plain` leaves "**Highlights")."""
        return bool(self.heading.search(_MARKS.sub("", plain(title)).strip()))


@dataclass(frozen=True)
class Found:
    """A box as a file writes it: whose it is, what it is written under (its heading's title,
    or its environment), the line it opens on, each item as printed, and its text as
    printed."""

    id: str
    title: str
    line: int
    items: tuple[str, ...]
    text: str
    #: The text as written, comments blanked, for the headings a box must carry.
    written: str = field(default="", compare=False)


def box_rules(document: dict) -> tuple[list[BoxRule], list[dict]]:
    """The boxes a profile asks for, and those whose heading is no regular expression."""
    rules: list[BoxRule] = []
    invalid: list[dict] = []
    for entry in document.get("boxes") or ():
        if not isinstance(entry, dict) or not entry.get("id") or not entry.get("heading"):
            continue
        try:
            heading = re.compile(str(entry["heading"]), re.IGNORECASE)
        except re.error:
            invalid.append(entry)
            continue
        environment = str(entry.get("environment") or str(entry["id"]).replace("-", ""))
        rules.append(BoxRule(str(entry["id"]), heading, environment))
    return rules, invalid


def box_of(title: str, rules: list[BoxRule]) -> BoxRule | None:
    """The first box whose heading `title` is, or None."""
    return next((rule for rule in rules if rule.names(title)), None)


def printed(raw: str, namespace: dict[str, Any]) -> str:
    """A stretch of Markdown as the build prints it: each value binding its display, an
    anchor nothing, a link its text, Markdown's marks off, white space folded."""
    placeholders, _ = parse(raw)
    out = raw
    for placeholder in sorted(placeholders, key=lambda p: p.start, reverse=True):
        if placeholder.is_anchor:
            replacement = ""
        elif placeholder.is_value and placeholder.ref in namespace:
            replacement = str(namespace[placeholder.ref].display)
        else:
            continue
        out = out[: placeholder.start] + replacement + out[placeholder.end :]
    out = _LINK.sub(r"\1", out)
    return _SPACE.sub(" ", _MARKS.sub("", out)).strip()


def words(text: str) -> int:
    """A box's words, counted as G4 counts the main text's."""
    return count_words(text)


# ------------------------------------------------------------------------------ Markdown


def markdown_boxes(text: str, rules: list[BoxRule], namespace: dict[str, Any]) -> list[Found]:
    """Each box a Markdown file writes, in its order: a section whose heading names a box."""
    if not rules:
        return []
    head = front_matter_end(text)
    # The front matter blanked, its line breaks kept, so that a line is the file's.
    read = re.sub(r"[^\n]", " ", text[:head]) + scannable(text[head:])
    found: list[Found] = []
    for section in split_sections(read):
        rule = box_of(section.title, rules) if section.level else None
        if rule is None:
            continue
        items = tuple(printed(item, namespace) for item in markdown_items(section.enclosed))
        found.append(
            Found(
                rule.id,
                section.title,
                section.line,
                tuple(item for item in items if item),
                printed(_unmarked_lines(section.enclosed), namespace),
                section.enclosed,
            )
        )
    return found


def _unmarked_lines(body: str) -> str:
    """A box's text without what opens a line and prints no word: a list's marks, a
    sub-heading's `#`s and an underline. An ordered list's "1." was otherwise a word."""
    lines = []
    for line in body.split("\n"):
        if re.match(r"^ {0,3}(?:=+|-+)[ \t]*$", line):
            continue
        started = _ITEM.match(line)
        if started:
            line = started.group(1) or ""
        lines.append(re.sub(r"^ {0,3}#{1,6}(?:[ \t]+|$)", "", line))
    return "\n".join(lines)


def markdown_items(body: str) -> list[str]:
    """The items of a box written in Markdown: its list's, or, where it has no list, its
    paragraphs. A sub-heading is neither."""
    items: list[str] = []
    paragraphs: list[str] = []
    current: list[str] | None = None
    paragraph: list[str] = []
    blank = False
    for line in body.split("\n"):
        started = _ITEM.match(line)
        if _HEADING_LINE.match(line):
            current, blank = None, False
            paragraph = _closed(paragraph, paragraphs)
            continue
        if started:
            current = [started.group(1) or ""]
            items.append("")
            paragraph = _closed(paragraph, paragraphs)
        elif not line.strip():
            blank = True
            paragraph = _closed(paragraph, paragraphs)
            continue
        elif current is not None and (not blank or line.startswith(("  ", "\t"))):
            current.append(line)
        else:
            current = None
            paragraph.append(line)
        if current is not None:
            items[-1] = "\n".join(current)
        blank = False
    _closed(paragraph, paragraphs)
    return items if items else paragraphs


def _closed(paragraph: list[str], paragraphs: list[str]) -> list[str]:
    if paragraph:
        paragraphs.append("\n".join(paragraph))
    return []


# --------------------------------------------------------------------------------- LaTeX


def latex_boxes(source: Any, rules: list[BoxRule], namespace: dict[str, Any]) -> list[Found]:
    """Each box a LaTeX file writes, in its order: a box's environment, or a section whose
    heading names a box. `source` is a file of the document as `text/latex/structure.py`
    reads it."""
    if not rules:
        return []
    found: list[tuple[int, Found]] = []
    for start, end, rule, title in latex_spans(source, rules):
        found.append((start, _latex_found(source, start, end, rule, title, namespace)))
    return [one for _start, one in sorted(found, key=lambda pair: pair[0])]


def latex_spans(source: Any, rules: list[BoxRule]) -> list[tuple[int, int, BoxRule, str]]:
    """Where each box of a LaTeX file runs: from its `\\begin` to its `\\end`, or from its
    heading to the next heading of its level or above, with the box and its title."""
    reading, text = source.reading, source.text
    passed = _passed_over(reading)
    spans = environment_spans(source, rules)
    headings = [h for h in reading.headings if h.level and h.end >= 0]
    last = reading.body_end if reading.body_end >= 0 else len(text)
    for index, heading in enumerate(headings):
        rule = box_of(heading.title, rules)
        if rule is None or passed(heading.start):
            continue
        closes = next((later.start for later in headings[index + 1 :]
                       if later.level <= heading.level), last)  # fmt: skip
        spans.append((heading.end, closes, rule, heading.title))
    return spans


def environment_spans(source: Any, rules: list[BoxRule]) -> list[tuple[int, int, BoxRule, str]]:
    """Where each box a LaTeX file writes in its environment runs, `\\begin` to `\\end`."""
    reading, text = source.reading, source.text
    passed = _passed_over(reading)
    spans: list[tuple[int, int, BoxRule, str]] = []
    for rule in rules:
        name = re.escape(rule.environment)
        ending = re.compile(r"\\end\s*\{" + name + r"\}")
        for opened in re.finditer(r"\\begin\s*\{" + name + r"\}", text):
            if passed(opened.start()):
                continue
            closed = next((m.start() for m in ending.finditer(text, opened.end())
                           if not passed(m.start())), len(text))  # fmt: skip
            spans.append((opened.end(), closed, rule, rule.environment))
    return spans


def _passed_over(reading: Any):
    """Whether an offset of a file is in what TeX prints nothing of: a comment, an
    `\\iffalse` block or a definition's body."""
    spans = [*reading.comments, *reading.unprinted, *reading.bodies]
    return lambda at: any(start <= at < end for start, end in spans)


def _latex_found(source: Any, start: int, end: int, rule: BoxRule, title: str,
                 namespace: dict[str, Any]) -> Found:  # fmt: skip
    text, reading = source.text, source.reading
    passed = _passed_over(reading)
    starts = [m for m in _LATEX_ITEM.finditer(text, start, end) if not passed(m.start())]
    items: list[str] = []
    for index, item in enumerate(starts):
        stop = starts[index + 1].start() if index + 1 < len(starts) else end
        listed = _LATEX_LIST_END.search(text, item.end(), stop)
        items.append(latex_printed(source, item.end(), listed.start() if listed else stop,
                                   namespace))  # fmt: skip
    if not starts:
        items = [latex_printed(source, a, b, namespace) for a, b in _paragraphs(reading.masked,
                                                                              start, end)]
    body = latex_printed(source, start, end, namespace)
    line = text.count("\n", 0, start) + 1
    return Found(rule.id, title, line, tuple(item for item in items if item), body, body)


def latex_printed(source: Any, start: int, end: int, namespace: dict[str, Any]) -> str:
    """What a stretch of a LaTeX file prints, as G4 reads it: its prose as the mask leaves
    it, each binding its value's display, white space folded."""
    masked = source.reading.masked
    out: list[str] = []
    at = start
    for use in sorted(source.reading.bindings, key=lambda b: b.start):
        if use.start < at or use.start >= end:
            continue
        out.append(masked[at : use.start])
        inner = use.inner or ""
        value = namespace.get(inner)
        out.append(str(value.display) if value is not None else "{{" + inner + "}}")
        at = use.end
    out.append(masked[at:end] if at < end else "")
    return _SPACE.sub(" ", "".join(out).replace(_NUL, "")).strip()


def _paragraphs(masked: str, start: int, end: int) -> list[tuple[int, int]]:
    """Where each paragraph of `masked` between `start` and `end` runs: a line that prints
    nothing ends one."""
    spans: list[tuple[int, int]] = []
    opened = None
    at = start
    for line in masked[start:end].split("\n"):
        empty = not line.replace(_NUL, "").strip()
        if empty and opened is not None:
            spans.append((opened, at))
            opened = None
        elif not empty and opened is None:
            opened = at
        at += len(line) + 1
    if opened is not None:
        spans.append((opened, min(at, end)))
    return spans
