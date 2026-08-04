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

_ATX = re.compile(r"^(?P<hashes>#{1,6})\s+(?P<title>.+?)\s*#*$", re.MULTILINE)

# Setext: a line of text underlined with `=` (level 1) or `-` (level 2). Pandoc renders
# these, and nothing here saw them — so a manuscript written in that style had no sections
# at all as far as G2, G4 and the reporting gate were concerned: no required-section check,
# no abstract, and every `methods_only` rule silently inapplicable.
#
# The underline is `=+` or `-{3,}`. Three dashes rather than one, because a shorter run is
# more often a stray than a heading, and because `---` closing YAML front matter would
# otherwise turn its last line into a heading — which is why `_scannable` blanks the front
# matter before any of this runs.
_SETEXT = re.compile(
    r"^(?P<title>(?![ \t]*$)(?![ \t]*[-=]+[ \t]*$)(?![ \t]*[#>|])[^\n]+)\n"
    r"(?P<under>=+|-{3,})[ \t]*$",
    re.MULTILINE,
)

# Kept as the ATX pattern for callers that only ever meant `#` headings.
HEADING = _ATX

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


_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


def _scannable(text: str) -> str:
    """`text` with code fences and HTML comments blanked, offsets preserved.

    Headings are found by scanning for `^#{1,6}\\s`, and `#` is a comment character in
    Python, R, shell and YAML. Once fenced code stopped being masked — correctly, because it
    renders — an ordinary comment inside a listing became a heading:

        ## Methods
        ```python
        # Methods          <- level 1, so it *pops* the real level-2 Methods
        ```
        ## Results
        The excess was significant (p < 0.001).   <- nests under the fake heading

    `is_methods` looks at the whole enclosing chain, so a threshold in the Results was
    accepted as the alpha chosen in advance. No attacker required: that is a comment
    character in a code block. An HTML comment does the same thing while being invisible in
    the rendered document, which is worse.

    Blanked rather than removed, because callers index back into the original text.
    Newlines are kept so line numbers and `^` anchors still line up.
    """

    def blank(match: re.Match[str]) -> str:
        return "".join("\n" if ch == "\n" else " " for ch in match.group(0))

    out = _HTML_COMMENT.sub(blank, _FENCED_CODE.sub(blank, text))
    # Front matter too, now that setext headings are recognised: its closing `---` sits
    # directly under a YAML line, which would otherwise read as `key: value` underlined —
    # a level-2 heading conjured out of the document's own delimiter.
    opening = FRONTMATTER.match(out)
    return blank(opening) + out[opening.end() :] if opening else out


@dataclass(frozen=True)
class _Found:
    start: int
    level: int
    title: str


def _headings_in(text: str) -> list[_Found]:
    """Every heading, ATX and setext, in document order."""
    scannable = _scannable(text)
    found = [
        _Found(m.start(), len(m.group("hashes")), m.group("title").strip())
        for m in _ATX.finditer(scannable)
    ]
    found += [
        _Found(m.start(), 1 if m.group("under").startswith("=") else 2, m.group("title").strip())
        for m in _SETEXT.finditer(scannable)
    ]
    return sorted(found, key=lambda f: f.start)


def section_chain(text: str, offset: int) -> tuple[str, ...]:
    """Every heading enclosing `offset`, outermost first.

    A chain rather than the nearest heading, because the nearest one is often a subsection
    whose own title says nothing: `### Sensitivity analyses` under `## Methods` is still
    Methods, and answering with just "Sensitivity analyses" would make a threshold stated
    there look like a reported result.

    Used by G2 to ask where a number sits, since two rules mean different things in
    different places: `p < 0.05` in Methods is the alpha the author chose, and in Results
    it is a finding.
    """
    stack: list[tuple[int, str]] = []
    for found in _headings_in(text):
        if found.start > offset:
            break
        while stack and stack[-1][0] >= found.level:
            stack.pop()
        stack.append((found.level, found.title))
    return tuple(title for _level, title in stack)


def split_sections(text: str) -> list[Section]:
    """Top-level structure. Subsections stay inside their parent's body."""
    matches = _headings_in(text)
    if not matches:
        return [Section(title="", level=0, body=text, line=1)]

    sections: list[Section] = []
    preamble = text[: matches[0].start].strip()
    if preamble:
        sections.append(Section(title="", level=0, body=preamble, line=1))

    for index, found in enumerate(matches):
        end = matches[index + 1].start if index + 1 < len(matches) else len(text)
        # Past the heading itself: the `#` line, or the title plus its underline.
        body_from = text.find("\n", found.start)
        if body_from != -1 and found.level and text[found.start] != "#":
            body_from = text.find("\n", body_from + 1)
        sections.append(
            Section(
                title=found.title,
                level=found.level,
                body=text[(body_from if body_from != -1 else found.start) : end],
                line=text.count("\n", 0, found.start) + 1,
            )
        )
    return sections


def headings(text: str) -> list[str]:
    return [found.title for found in _headings_in(text)]


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
