"""Sections and word counts.

Journals impose limits, and a limit is only checkable if both sides agree on what is being
counted. They rarely say precisely, so the rule used here is written down and reported
alongside the number rather than left implicit:

* Words are whitespace-separated tokens after Markdown syntax, citations, images, tables
  and code have been removed. A citation is not a word the author wrote; a table's contents
  are counted separately by every journal that counts them at all.
* The abstract and the references are counted separately from the main text, because every
  journal treats them separately.
* Headings count towards the main text, because they are printed.

Where a journal counts differently, the profile can say so. Where it does not say, the
count is reported with the rule, so a disagreement is visible rather than mysterious.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from manuscript_guard.text.masking import FRONTMATTER, mask

HEADING = re.compile(r"^(?P<hashes>#{1,6})\s+(?P<title>.+?)\s*#*$", re.MULTILINE)

_ABSTRACT = re.compile(r"^\s*(?:structured\s+)?abstract\b", re.IGNORECASE)
_REFERENCES = re.compile(r"^\s*(?:references|bibliography|works cited)\b", re.IGNORECASE)

_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$", re.MULTILINE)
_TABLE_CAPTION = re.compile(r"^\s*:\s+.+$", re.MULTILINE)
_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")

# Code, stripped here rather than borrowed from `mask()`. The two were sharing one answer to
# two different questions — "where is a digit not a claim?" and "what would a journal count?"
# — and the answers have now diverged: inline code and fenced blocks render, so G2 reads
# them, while a journal counting body prose does not count a code listing. Sharing the mask
# meant widening the gate silently changed every word count in the toolkit.
_FENCED_CODE = re.compile(
    r"^[ \t]*(`{3,}|~{3,})[^\n]*\n.*?^[ \t]*\1[ \t]*$", re.DOTALL | re.MULTILINE
)
_INLINE_CODE = re.compile(r"`[^`\n]+`")
_MD_SYNTAX = re.compile(r"[*_`~>#\[\]|]")


@dataclass(frozen=True)
class Section:
    title: str
    level: int
    body: str
    line: int

    @property
    def is_abstract(self) -> bool:
        return bool(_ABSTRACT.match(self.title))

    @property
    def is_references(self) -> bool:
        return bool(_REFERENCES.match(self.title))


def split_sections(text: str) -> list[Section]:
    """Top-level structure. Subsections stay inside their parent's body."""
    matches = list(HEADING.finditer(text))
    if not matches:
        return [Section(title="", level=0, body=text, line=1)]

    sections: list[Section] = []
    preamble = text[: matches[0].start()].strip()
    if preamble:
        sections.append(Section(title="", level=0, body=preamble, line=1))

    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections.append(
            Section(
                title=match.group("title").strip(),
                level=len(match.group("hashes")),
                body=text[match.end() : end],
                line=text.count("\n", 0, match.start()) + 1,
            )
        )
    return sections


def headings(text: str) -> list[str]:
    return [m.group("title").strip() for m in HEADING.finditer(text)]


def count_words(text: str) -> int:
    """Words a journal would count: prose, without citations, tables, images or markup."""
    # Front matter goes whole, for the same reason: G2 now reads the title and abstract out
    # of it because pandoc renders them, but a journal counts those against their own limits,
    # not against the body.
    opening = FRONTMATTER.match(text)
    stripped = text[opening.end() :] if opening else text
    stripped = _FENCED_CODE.sub(" ", stripped)
    stripped = _INLINE_CODE.sub(" ", stripped)
    stripped = mask(stripped)  # removes citations, URLs, placeholders
    stripped = stripped.replace("\x00", " ")
    stripped = _IMAGE.sub(" ", stripped)
    stripped = _TABLE_ROW.sub(" ", stripped)
    stripped = _TABLE_CAPTION.sub(" ", stripped)
    stripped = _MD_SYNTAX.sub(" ", stripped)
    return len([token for token in stripped.split() if any(c.isalnum() for c in token)])


@dataclass(frozen=True)
class Counts:
    abstract_words: int
    main_text_words: int
    total_words: int
    sections: tuple[str, ...]
    tables: int
    figures: int


def measure(text: str) -> Counts:
    """Counts over manuscript source, before bindings are substituted.

    Counting the source rather than the built document means a binding counts as one word
    whatever it resolves to. That is close enough for a limit, and it means the count does
    not change when the analysis is re-run.
    """
    sections = split_sections(text)
    abstract = sum(count_words(s.body) for s in sections if s.is_abstract)
    main = sum(
        count_words(s.body) + count_words(s.title)
        for s in sections
        if not s.is_abstract and not s.is_references
    )
    return Counts(
        abstract_words=abstract,
        main_text_words=main,
        total_words=abstract + main,
        sections=tuple(s.title for s in sections if s.title),
        tables=len(re.findall(r"\{\{table\.[a-z0-9_.]+\}\}", text)),
        figures=len(re.findall(r"\{\{figure\.[a-z0-9_.]+\}\}", text)),
    )
