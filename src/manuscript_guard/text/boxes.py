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

#: A line that opens an item of a Markdown list, at any indentation: what indents it, its
#: mark, the space after the mark and the item's text. Whether it is an item of the box's list
#: or of a list nested in one of them is the indentation's to say (`_nested`).
_ITEM = re.compile(
    r"^(?P<indent> *)(?P<mark>[-*+]|\d{1,9}[.)])(?:(?P<gap>[ \t]+)(?P<text>.*)|[ \t]*)$"
)
#: A line of a Markdown heading, which is no part of an item or a paragraph.
_HEADING_LINE = re.compile(r"^ {0,3}#{1,6}(?:[ \t]|$)|^ {0,3}(?:=+|-+)[ \t]*$")
#: A Markdown link or image, printed as its text.
_LINK = re.compile(r"!?\[([^\]\n]*)\]\([^)\n]*\)")
#: Markdown's emphasis and code marks, at the edge of a word.
_MARKS = re.compile(r"(?<!\w)[*_]+|[*_]+(?!\w)|`+")
_SPACE = re.compile(r"\s+")
#: A LaTeX list's item, and where a list opens and closes, which says how deep an item is.
_LATEX_LIST = re.compile(
    r"\\(?P<which>begin|end)\s*\{(?P<kind>itemize|enumerate|description)\*?\}"
    r"|\\item(?![A-Za-z@])"
)
#: An optional argument's `[`, past the spaces and the one line break TeX passes over.
_OPTION = re.compile(r"[ \t]*(?:\n[ \t]*)?\[")
#: A thematic break, three or more of one mark with spaces or none, which is no item.
_BREAK = re.compile(r"^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$")
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
        if re.match(r"^ {0,3}(?:=+|-+)[ \t]*$", line) or _BREAK.match(line.expandtabs(4)):
            continue
        started = _ITEM.match(line.expandtabs(4))
        if started:
            line = started["text"] or ""
        lines.append(re.sub(r"^ {0,3}#{1,6}(?:[ \t]+|$)", "", line))
    return "\n".join(lines)


def markdown_items(body: str) -> list[str]:
    """The items of a box written in Markdown: its list's, or, where it has no list, its
    paragraphs. A sub-heading is neither. An item of a list nested in an item is that item's
    text, as it prints inside it: "- A" over "  - a1" is one item."""
    items: list[str] = []
    paragraphs: list[str] = []
    current: list[str] | None = None
    column = 0
    paragraph: list[str] = []
    blank = False
    for line in (raw.expandtabs(4) for raw in body.split("\n")):
        started = _ITEM.match(line)
        if _HEADING_LINE.match(line) or _BREAK.match(line):
            # A sub-heading, and a thematic break (`- - -`, `***`), end a list and are none.
            current, blank = None, False
            paragraph = _closed(paragraph, paragraphs)
            continue
        nested = started is not None and current is not None and _nested(started, column)
        if started and not nested and (current is not None or len(started["indent"]) <= 3):
            current = [started["text"] or ""]
            column = _content_column(started)
            items.append("")
            paragraph = _closed(paragraph, paragraphs)
        elif not line.strip():
            blank = True
            paragraph = _closed(paragraph, paragraphs)
            continue
        elif current is not None and nested:
            current.append(started["text"] or "")
        elif current is not None and _runs_on(line, column, blank):
            current.append(line)
        else:
            current = None
            paragraph.append(line)
        if current is not None:
            items[-1] = "\n".join(current)
        blank = False
    _closed(paragraph, paragraphs)
    return items if items else paragraphs


def _content_column(started: re.Match[str]) -> int:
    """Where an item's text starts, as CommonMark and pandoc place it: past its indentation,
    its mark and the space after it, one space where the text starts five or more past the
    mark (an indented listing then), or the item has none."""
    gap = len(started["gap"] or "")
    return len(started["indent"]) + len(started["mark"]) + (gap if 1 <= gap <= 4 else 1)


def _nested(started: re.Match[str], column: int) -> bool:
    """Whether an item opened while another is open is of a list nested in that one: its
    mark indented as far as the open item's text (`column`). Less is an item of the same
    list, whatever the list's own indentation."""
    return len(started["indent"]) >= column


def _runs_on(line: str, column: int, blank: bool) -> bool:
    """Whether a line that opens no item is text of the open item: straight after it, as a
    lazy line of its paragraph, or after a blank line indented to its text (`column`), as
    CommonMark reads it. Less indented after a blank line, it is a paragraph after the list
    (round 2 of #464: "1. A", a blank line, then "  B" joined B to A)."""
    return not blank or len(line) - len(line.lstrip(" ")) >= column


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
    headings = sorted(reading.headings, key=lambda h: h.start)
    last = reading.body_end if reading.body_end >= 0 else len(text)
    for index, heading in enumerate(headings):
        rule = box_of(heading.title, rules) if _titled(heading) else None
        if rule is None or passed(heading.start):
            continue
        closes = next((later.start for later in headings[index + 1 :]
                       if _closes(later, heading)), last)  # fmt: skip
        spans.append((heading.end, closes, rule, heading.title))
    return spans


def _titled(heading: Any) -> bool:
    """Whether a heading of a LaTeX file has a title a box may be named by: a sectioning
    command's, a part's and a chapter's among them. An abstract's has none (`end` -1)."""
    return heading.end >= 0


def _closes(later: Any, heading: Any) -> bool:
    """Whether a heading after a box's ends the box: one of its level or above, or an
    abstract, which the printed view reads as a section of its own whatever the box's level
    (round 1 of #464: an abstract after the box was read as its last items)."""
    return later.end < 0 or later.level <= heading.level


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
    spans = latex_item_spans(text, start, end, passed)
    # A list's options print nothing, whatever the mask leaves of them.
    omit = list_options(text, start, end, passed)
    items = [latex_printed(source, a, b, namespace, omit) for a, b in spans]
    if not spans:
        items = [latex_printed(source, a, b, namespace, omit)
                 for a, b in _paragraphs(reading.masked, start, end)]  # fmt: skip
    body = latex_printed(source, start, end, namespace, omit)
    line = text.count("\n", 0, start) + 1
    return Found(rule.id, title, line, tuple(item for item in items if item), body, body)


def latex_item_spans(text: str, start: int, end: int, passed) -> list[tuple[int, int]]:
    """Where each item of a box's own list runs, from past its `\\item` to the next item of
    that list or the `\\end` that closes the list. An `\\item` of a list nested in an item
    is that item's text, as it prints inside it: the box's items are those of the least
    depth, the depth of an environment that is itself a list (Elsevier's highlights) 0."""
    marks: list[tuple[int, int, int, str]] = []  # (start, end, depth, item / end)
    lists: list[str] = []
    for found in _LATEX_LIST.finditer(text, start, end):
        if passed(found.start()):
            continue
        if found["which"] == "begin":
            lists.append(found["kind"])
        elif found["which"] == "end":
            marks.append((found.start(), found.end(), len(lists), "end"))
            lists = lists[:-1]
        else:
            # An itemize's or an enumerate's label (`\item[--]`) is its mark, and no text of
            # the item; a description's is its term, printed with it.
            kind = lists[-1] if lists else ""
            after = found.end() if _label_counts(kind) else _past_option(text, found.end(), end)
            marks.append((found.start(), after, len(lists), "item"))
    top = min((depth for _a, _b, depth, kind in marks if kind == "item"), default=0)
    spans: list[tuple[int, int]] = []
    for index, (_at, after, depth, kind) in enumerate(marks):
        if kind != "item" or not _of_the_box(depth, top):
            continue
        # The next item of its list, or the `\end` of its list, recorded at its depth.
        stop = next((at for at, _after, later, _kind in marks[index + 1 :]
                     if later == depth), end)  # fmt: skip
        spans.append((after, stop))
    return spans


def _of_the_box(depth: int, top: int) -> bool:
    """Whether an `\\item` as deep as `depth` is an item of the box, whose own are `top`
    deep: a deeper one is of a list nested in an item."""
    return depth == top


def _label_counts(kind: str) -> bool:
    """Whether an `\\item`'s label is text of its item: a description's term is; an
    itemize's or an enumerate's mark, or that of a box's own environment, is not."""
    return kind == "description"


def _past_option(text: str, at: int, end: int) -> int:
    """Past an optional argument that opens at `at`, spaces and one line break before it
    as TeX reads them, to the `]` that closes it outside braces; `at` where none opens, or
    none closes before a blank line or `end`."""
    opened = _OPTION.match(text, at, end)
    if opened is None:
        return at
    depth = 0
    for index in range(opened.end(), end):
        character = text[index]
        if character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
        elif character == "]" and depth == 0:
            return index + 1
        elif character == "\n" and text.startswith("\n", index + 1):
            return at
    return at


def list_options(text: str, start: int, end: int, passed) -> list[tuple[int, int]]:
    """Where each list of a box writes its options (`\\begin{itemize}[noitemsep]`), which
    print nothing."""
    spans = []
    for found in _LATEX_LIST.finditer(text, start, end):
        if found["which"] == "begin" and not passed(found.start()):
            after = _past_option(text, found.end(), end)
            if after > found.end():
                spans.append((found.end(), after))
    return spans


def latex_printed(source: Any, start: int, end: int, namespace: dict[str, Any],
                  omit: list[tuple[int, int]] = ()) -> str:  # fmt: skip
    """What a stretch of a LaTeX file prints, as G4 reads it: its prose as the mask leaves
    it, each binding its value's display, white space folded; what `omit` names, a list's
    options, left out."""
    masked = source.reading.masked
    for a, b in omit:
        if a < end and b > start:
            masked = masked[:a] + " " * (b - a) + masked[b:]
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
