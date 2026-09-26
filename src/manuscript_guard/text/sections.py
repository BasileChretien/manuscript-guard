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
* The YAML front matter does not count, rendered keys included. The build strips it and
  prints the title from paper.yaml, so none of it is in the document a limit is about.

Where a journal counts differently, the profile can say so. Where it does not say, the
count is reported with the rule, so a disagreement is visible rather than mysterious.
"""

from __future__ import annotations

import re
from bisect import bisect_right
from dataclasses import dataclass

from manuscript_guard.text.attributes import strip_attributes
from manuscript_guard.text.blocks import (
    Heading,
    Unprinted,
    find_headings,
    scannable,
    section_breaks,
)
from manuscript_guard.text.fences import blank_fences
from manuscript_guard.text.masking import mask, without_front_matter

# `scannable` moved to `text.blocks` with the heading walk, and `strip_attributes` to
# `text.attributes` so the walk can title headings with it; both are re-exported for the
# callers that learned them here.
__all__ = [
    "Chain",
    "Counts",
    "HeadingIndex",
    "Section",
    "chain_at",
    "count_words",
    "heading_index",
    "headings",
    "measure",
    "scannable",
    "section_chain",
    "split_sections",
    "strip_attributes",
    "subsections",
]

# Headings are found by `text.blocks`, which reads them as pandoc does: ATX and setext, and
# only where a block starts. Setext mattered because a manuscript written in that style had
# no sections at all as far as G2, G4 and the reporting gate were concerned: no
# required-section check, no abstract, and every `methods_only` rule silently inapplicable.

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
_INLINE_CODE = re.compile(r"`[^`\n]+`")
_MD_SYNTAX = re.compile(r"[*_`~>#\[\]|]")


@dataclass(frozen=True)
class Section:
    title: str
    level: int
    #: The section's own text, up to the next heading of any level. The bodies of a
    #: document's sections partition it, so they can be summed without counting twice.
    body: str
    line: int
    #: Everything under the heading, subsections included: up to the next heading at this
    #: level or above. What a caller asking for "the Methods" means.
    enclosed: str = ""

    @property
    def is_abstract(self) -> bool:
        return bool(_ABSTRACT.match(self.title))

    @property
    def is_references(self) -> bool:
        return bool(_REFERENCES.match(self.title))


def heading_index(text: str) -> list[Heading]:
    """Every section break, computed once so a caller can ask about many offsets cheaply.

    `section_chain` rescans the whole document — blanking fences, HTML comments and front
    matter, then walking it line by line. G2 called it once per atom, which is quadratic: a
    paragraph written on one long line with 20,000 numbers spent three minutes re-deriving
    the same heading list 20,000 times. The scan is unavoidable; doing it per file rather
    than per number is not.

    The printed headings, and the lines shaped like headings that pandoc prints as text,
    titled `Unprinted`: see `section_breaks`. For the headings a reader sees, as a word
    count or a required-section check wants them, use `split_sections` or `headings`.
    """
    return HeadingIndex(section_breaks(text))


class Chain(tuple):
    """The headings enclosing a place, outermost first, and `printed`: the same chain as a
    reader of the built document has it, from the headings pandoc prints alone and the lines
    printed as text that say Results.

    `is_methods` asks both. A line pandoc prints as text can end a section for the gates;
    counted alone, "# of reports" wrapped to the start of a line closed the Results, and a
    "Sensitivity analyses" under it read as Methods, where the reader sees it in the
    Results.
    """

    printed: tuple[str, ...]

    def __new__(cls, titles: tuple[str, ...], printed: tuple[str, ...]) -> Chain:
        chain = super().__new__(cls, titles)
        chain.printed = printed
        return chain


class HeadingIndex(list):
    """Section breaks in document order, with the chain after each worked out once.

    `chain_at` walked every heading before a number, for every number: 4,000 headings and
    12,000 numbers took 50 s in G2. Found by bisection, it is a lookup.
    """

    def __init__(self, headings: list[Heading]) -> None:
        from manuscript_guard.classify import rules_out_methods

        super().__init__(headings)
        self.starts = [found.start for found in self]
        self.chains: list[Chain] = []
        every: list[tuple[int, str]] = []
        printed: list[tuple[int, str]] = []
        for found in self:
            # A line printed as text stays off the printed chain, unless it says Results:
            # there it can only keep the Results in place. Off it, a later line printed as
            # text took it off the other chain as well, and left both saying Methods.
            both = type(found.title) is not Unprinted or rules_out_methods(found.title)
            for stack in (every, printed) if both else (every,):
                level = 1 if stack is printed and _hash_over_rule(found) else found.level
                while stack and stack[-1][0] >= level:
                    stack.pop()
                stack.append((level, found.title))
            self.chains.append(
                Chain(tuple(t for _l, t in every), tuple(t for _l, t in printed))
            )


def _hash_over_rule(found: Heading) -> bool:
    """A `# X` line over a `-` rule. Pandoc prints a level-2 heading titled "# X", which is
    how the walk places it, and the scan before the walk read a level-1 heading "X". Where
    the walk wrongly placed a `# Methods` above it, under a stray `</script>` say, the level-2
    reading nested under that Methods, and the level-1 one closes it. So the printed chain
    takes level 1, and both readings must say Methods."""
    return (
        found.setext
        and found.level == 2
        and found.title[:1] == "#"
        and found.title[1:2] in (" ", "\t", "")
    )


def chain_at(index: list[Heading], offset: int) -> Chain:
    """The enclosing heading chain at `offset`, from a precomputed index."""
    if not isinstance(index, HeadingIndex):
        index = HeadingIndex(index)
    before = bisect_right(index.starts, offset)
    return index.chains[before - 1] if before else Chain((), ())


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
    return chain_at(heading_index(text), offset)


def split_sections(text: str) -> list[Section]:
    """Every heading, in document order, each with its own text and everything under it.

    This used to say "subsections stay inside their parent's body" while the body stopped
    at the next heading of any level. Every caller that wanted a whole section got its
    first paragraphs: the design gate called a Population written under `### Inclusion` a
    heading with nothing under it, and a parameter stated under `## Statistical analysis`
    was reported absent from the Methods. Both answers are carried now — `body` to sum,
    `enclosed` to read — so no caller has to guess which one it was given.
    """
    matches = find_headings(text)
    if not matches:
        return [Section(title="", level=0, body=text, line=1, enclosed=text)]

    sections: list[Section] = []
    preamble = text[: matches[0].start].strip()
    if preamble:
        sections.append(Section(title="", level=0, body=preamble, line=1, enclosed=preamble))

    for index, found in enumerate(matches):
        end = matches[index + 1].start if index + 1 < len(matches) else len(text)
        closes = next(
            (later.start for later in matches[index + 1 :] if later.level <= found.level),
            len(text),
        )
        # Past the heading itself: the `#` line, or the title plus its underline. Asked of the
        # heading rather than its first character: `## Methods` over an underline is a
        # setext title to pandoc.
        body_from = text.find("\n", found.start)
        if body_from != -1 and found.setext:
            body_from = text.find("\n", body_from + 1)
        opens = body_from if body_from != -1 else found.start
        sections.append(
            Section(
                title=found.title,
                level=found.level,
                body=text[opens:end],
                line=text.count("\n", 0, found.start) + 1,
                enclosed=text[opens:closes],
            )
        )
    return sections


def subsections(sections: list[Section], index: int) -> list[Section]:
    """The section at `index` and every section nested under it, in order."""
    level = sections[index].level
    nested = [sections[index]]
    for later in sections[index + 1 :]:
        if later.level <= level:
            break
        nested.append(later)
    return nested


def headings(text: str) -> list[str]:
    return [found.title for found in find_headings(text)]


def count_words(text: str) -> int:
    """Words a journal would count: prose, without citations, tables, images or markup."""
    # Front matter goes whole, rendered keys included. G2 reads the title and abstract out of
    # it because pandoc renders them, but the build strips the block, and a journal counts a
    # title and an abstract against limits of their own, not against the body.
    stripped = blank_fences(without_front_matter(text))
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
    # The front matter goes before the split. `split_sections` trims the text before the
    # first heading, which takes the newline after the closing `---` with it, and without
    # that newline `count_words` no longer recognised the block: every word of the YAML,
    # keys included, counted as main text.
    printed = without_front_matter(text)
    sections = split_sections(printed)
    abstract = main = 0
    # Each section counts where its enclosing sections put it. Judged by its own title
    # alone, `## Background` under `# Abstract` was main text, so a structured abstract
    # written with headings escaped the abstract's limit.
    chain: list[Section] = []
    for section in sections:
        while chain and chain[-1].level >= section.level:
            chain.pop()
        chain.append(section)
        if any(s.is_references for s in chain):
            continue
        words = count_words(section.body)
        if section.is_abstract:
            abstract += words
        elif any(s.is_abstract for s in chain):
            abstract += words + count_words(section.title)
        else:
            main += words + count_words(section.title)
    return Counts(
        abstract_words=abstract,
        main_text_words=main,
        total_words=abstract + main,
        sections=tuple(s.title for s in sections if s.title),
        tables=len(re.findall(r"\{\{table\.[a-z0-9_.]+\}\}", printed)),
        figures=len(re.findall(r"\{\{figure\.[a-z0-9_.]+\}\}", printed)),
    )
