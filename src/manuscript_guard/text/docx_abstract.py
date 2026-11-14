"""The headings a Word paper is placed by, its Abstract's among them where the paper writes it
in a shape no heading style marks.

The audit places a .docx's lines under its heading styles, or under its typed titles where it
has none (`text.docx.typed_heading_levels`). Two shapes of the Abstract's heading are read
besides, where none of those headings names the Abstract (Basile, 2026-11-14, after four
papers of the real-paper corpus whose Abstract a reader sees and the audit did not):

* **A run-in label.** A paragraph that opens on "Abstract:" or "Abstract." and goes on
  (`section_names.run_in_abstract`), in no heading style, outside a table and not numbered by
  Word: the label is the heading, and the paragraph's own text, numbers and all, the first
  of the Abstract's. In a paper with heading styles and in one placed by its typed titles.
* **A line of its own.** In a paper with heading styles, a line whose words are the
  Abstract's name alone (`section_names.abstract_alone`), in bold or not, on a line a title
  can be typed as (`DocxText.typed`), so in no table's cell and no list Word numbers. A
  paper with no heading style reads it as a typed title already. The paper's other typed
  titles stay text; "Abstract" in plain type was one of them until docx-ecol-B2 (Basile,
  2026-11-14).

The Abstract ends where any section does, at the next heading, which it is given the level
of. Before that heading it ends at a title typed on a line of its own that is no part of it,
as `section_levels` places a structured abstract's parts (`section_names.abstract_end`),
the next heading's title read after them, so that a styled Introduction ends the parts
(`_closing`): in the corpus, the next heading was a title page's line or an empty paragraph
in a heading style, and the Introduction, the Abbreviations, the Author information or the
Acknowledgments typed in bold before it ended the Abstract for a reader. That title is a
heading too, at the same level, and the text under it is under it up to the next. With
neither after it, where it ends is not read, and the shape is not read either: the Abstract
would run to the end of the paper.

However its heading was read, a run-in "Keywords:" after the Abstract's own words, before
the next title, ends it (`text.docx.keywords_line`; Basile, 2026-11-15): the titles after it
are no parts of it, and where words stand after it before the next heading, it is a heading
"Keywords" of its own (`_keywords`).
"""

from __future__ import annotations

from dataclasses import dataclass

from manuscript_guard.text.section_names import (
    abstract_alone,
    abstract_end,
    names_abstract,
    run_in_abstract,
    run_in_keywords,
    section_name_alone,
)


@dataclass(frozen=True)
class Heading:
    """A heading a .docx's lines are placed under: its 0-based line in `DocxText.body`, its
    level and title, and whether it is the run-in label of a paragraph that goes on."""

    line: int
    level: int
    title: str
    run_in: bool = False


def placed_headings(document) -> tuple[Heading, ...]:
    """The headings a `DocxText` is placed by: its heading styles', or its typed titles' where
    it has none and they can be placed (`typed_heading_levels`), and the Abstract's where none
    of them names it and the paper writes it in one of the two shapes above."""
    from manuscript_guard.text.docx import typed_heading_levels

    body = document.body.split("\n")
    levels = document.heading_levels or typed_heading_levels(document) or ()
    found = [Heading(at, level, body[at]) for at, level in levels]
    if found and not any(names_abstract(heading.title) for heading in found):
        found = sorted([*found, *_abstract(document, body, found)],
                       key=lambda heading: heading.line)  # fmt: skip
    keywords = _keywords(document, body, found)
    if keywords is None:
        return tuple(found)
    return tuple(sorted([*found, keywords], key=lambda heading: heading.line))


def _opened(document, body: list[str], styled: bool) -> Heading | None:
    """The first line that is the Abstract's heading in one of the two shapes, at level 0
    for now; None where there is none."""
    numbered = {line - 1 for line, *_rest in document.numbering}
    for at, line in enumerate(body):
        if at in document.headings or at in document.cells or at in numbered:
            # A list Word numbers holds no Abstract's heading, though its lone item that
            # names another section is a typed title since #682, which may end one.
            continue
        label = run_in_abstract(line)
        if label is not None:
            return Heading(at, 0, label.rstrip(" :."), run_in=True)
        if styled and at in document.typed and abstract_alone(line):
            return Heading(at, 0, _titled(line))
    return None


def _abstract(document, body: list[str], found: list[Heading]) -> list[Heading]:
    """The Abstract's heading, and the typed title that ends it where one does before the
    next heading; none where neither ends it."""
    from manuscript_guard.text.docx import keywords_line

    opened = _opened(document, body, bool(document.heading_levels))
    if opened is None:
        return []
    later = [heading for heading in found if heading.line > opened.line]
    limit = later[0].line if later else len(body)
    level = later[0].level if later else 1
    titles = [(at, name) for at in sorted(document.typed)
              if opened.line < at < limit and (name := section_name_alone(body[at]))]  # fmt: skip
    ends = [at for at, _name in titles] + [limit]
    worded = [opened.run_in or _worded(body, opened.line, ends[0])] + [
        _worded(body, at, end) for (at, _name), end in zip(titles, ends[1:], strict=True)]
    closing = _closing([heading.title for heading in later[:1]])
    # A run-in "Keywords:" under the Abstract's own words ends it (Basile, 2026-11-15).
    start = opened.line if opened.run_in else opened.line + 1
    ended = [keywords_line(body, document.typed, start, ends[0]) is not None]
    end = abstract_end(["Abstract", *(name for _at, name in titles), *closing],
                       worded + [False] * len(closing),
                       ended=ended + [False] * (len(titles) + len(closing)))  # fmt: skip
    heading = Heading(opened.line, level, opened.title, opened.run_in)
    if end is not None and end <= len(titles):
        at = titles[end - 1][0]
        return [heading, Heading(at, level, _titled(body[at]))]
    return [heading] if later else []


def _keywords(document, body: list[str], found: list[Heading]) -> Heading | None:
    """The heading a run-in "Keywords:" under the Abstract's own words is read as, where it
    ends the Abstract (`text.docx.keywords_line`) and words stand after it before the next
    heading: "Keywords", at the Abstract's level, a run-in label like the Abstract's, the
    line's text the first under it. What stands under it up to the next heading is no
    Abstract's, and reports nothing (`auditing.abstract`): a paper's Introduction with no
    heading (docx-psych-B2 and docx-psych-A1 of the real-paper corpus; Basile, 2026-11-15).
    None where the next heading is deeper than the Abstract's, a part of it by its style."""
    from manuscript_guard.text.docx import keywords_line

    opened = next((one for one in found if names_abstract(one.title)), None)
    if opened is None:
        return None
    later = [one for one in found if one.line > opened.line]
    if later and later[0].level > opened.level:
        return None
    limit = later[0].line if later else len(body)
    start = opened.line if opened.run_in else opened.line + 1
    at = keywords_line(body, document.typed, start, limit)
    if at is None or not _worded(body, at, limit):
        return None
    label = run_in_keywords(body[at]) or "Keywords"
    return Heading(at, opened.level, label.rstrip(" :"), run_in=True)


def _titled(line: str) -> str:
    """A typed title as a heading's, as `init --from` writes it: its words, less a colon or a
    stop after them, "Abstract:" as "Abstract"."""
    return " ".join(line.split()).rstrip(" :.")


def _closing(titles: list[str]) -> list[str]:
    """The next heading's title, the name it holds alone where it holds one, read after the
    typed titles: a structured abstract's parts end at a styled Introduction as at a typed
    one. Read up to it alone, they ended nowhere, and the Abstract at its first part named,
    its own "Results" the paper's (round 1 of #683)."""
    return [section_name_alone(title) or title for title in titles]


def _worded(body: list[str], at: int, end: int) -> bool:
    return any(body[k].strip() for k in range(at + 1, end))
