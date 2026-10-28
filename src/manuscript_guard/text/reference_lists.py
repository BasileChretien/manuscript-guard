"""Where a reference list starts: a heading that names one, and a line that only looks like
one.

The audit cuts a paper's reference list at its heading, and a line with a heading's shape
counts there: "References" alone on its line, in bold or not. `check` knew only the heading,
`# References`. A paper converted from Word has its list under a bold paragraph as often as
under a heading, `**References**` or `**References:**`, and G14 read that list as prose: it
checked the spelling of the cited titles and took journal names and authors' initials for
abbreviations ("PLoS", "BMC", "HA MB RM"). The audit's rule is said once, here, and both read
by it: `is_bibliography_heading` for a line, `unmarked_reference_lists` for where such a
line's list runs in a Markdown file.
"""

from __future__ import annotations

import re
from bisect import bisect_right

from manuscript_guard.text.attributes import strip_attributes
from manuscript_guard.text.blocks import find_headings, heading_shaped, scannable
from manuscript_guard.text.section_names import REFERENCE_WORDS_ELSEWHERE, STATEMENT_NAMES

# A line that is nothing but a bibliography heading, perhaps numbered, perhaps in bold. From
# there to the next heading is page ranges, volume numbers and years belonging to other
# people's papers: not the author's claims, and reporting them buries the findings that
# matter.
#
# Everything after the heading word is one character class under one quantifier. The first
# version had five optional whitespace runs in a row there, and a line that began with the
# word and failed later backtracked through every way of dividing its spaces between them:
# 26 s for one line of the kind `pdftotext -layout` writes.
#
# And every run of whitespace before the word has exactly one quantifier that can take it:
# the line is stripped first, and a number takes the spaces after it. With `^\s*` beside
# `[\s*_]*` a failing line was still quadratic in its indentation, and `pdftotext -layout`
# indents a right-hand column by a hundred spaces: 20 s for 3,000 such lines.
#
# A pandoc attribute block after the word, `{-}` or `{#refs .unnumbered}`, is not matched
# here. It is taken off a marked heading before the match, by `strip_attributes`, which reads
# it item by item, so this pattern keeps one quantifier after the word.
#
# A number's full stop may be escaped, `6\. References`: pandoc writes a numbered title
# paragraph of a Word document so, that it be no list item.
_BIBLIOGRAPHY = re.compile(
    r"^(?P<hashes>#+)?[\s*_]*"
    r"(?:(?P<numbered>\d+\\?[.)])[\s*_]*|(?P<bare>\d+)\s[\s*_]*)?"
    r"(?P<word>references(?:\s+cited)?|reference\s+list|list\s+of\s+references"
    r"|cited\s+references|bibliography|works\s+cited|literature\s+cited|cited\s+literature"
    rf"|{REFERENCE_WORDS_ELSEWHERE})"
    r"(?P<tail>[\s*_:.|]*)$",
    re.IGNORECASE,
)


def is_bibliography_heading(
    line: str, *, marked: bool = False, markdown: bool = True
) -> bool:
    """A bibliography heading: a line that is marked as a heading, or has a heading's shape.

    `marked` is for a line the document itself calls a heading, a Markdown `#` or setext
    heading or a styled paragraph in a .docx. Any other line has to look like one:
    capitalised, and not ending in a full stop. "12 references." and "references." are where
    a hard wrap left the end of a sentence, and taking either for a heading hid the rest of
    the section.

    A marked line is read without the attribute block at its end, as pandoc reads it.
    Pandoc users write an unnumbered reference heading as `# References {-}`, and the audit
    found no heading there: it cut nothing, and every number in a book or a web page in the
    list was reported among the findings. On an unmarked line the braces are printed, so
    "References {-}" there is text. Only spaces and tabs may follow the block: `strip()`
    takes every Unicode space, and a no-break space after `{-}`, which pandoc prints braces
    and all, cut a list.

    `markdown` says whether the marks are Markdown's. There a marked line opening with `#`
    is an ATX heading and loses its closing `#`s. A setext heading reading "References #"
    prints the `#`, and so does a .docx, where a style marks the heading and Word prints
    every `#` in "# References #".

    An unmarked line starting with `#` is not one at all. `#` opens a comment in R, Python
    and YAML, and `# References` in a code listing cut everything after it; where `#` does
    make a heading, the document has marked it.
    """
    text = line.strip()
    if marked:
        text = strip_attributes(line.lstrip().rstrip(" \t"))
        if markdown and text.startswith("#"):
            text = text.rstrip("#").rstrip(" \t")
        text = text.strip()
    found = _BIBLIOGRAPHY.match(text)
    if not found:
        return False
    if marked:
        return True
    if found.group("hashes"):
        return False
    return found.group("word")[0].isupper() and "." not in found.group("tail")


def unmarked_reference_lists(text: str) -> list[tuple[int, int]]:
    """Where a Markdown file's reference lists run under a line that is no heading, as offsets
    `[start, end)`.

    The line is one `is_bibliography_heading` takes unmarked, as the audit takes it: the word
    alone on its line, in bold or not, capitalised and not ending in a full stop. And it opens
    a paragraph, under a blank line, a heading or nothing, where the audit takes it anywhere:
    a sentence a hard wrap broke before "References" and after it has the word alone on a
    line, and taken for a list it would hide the rest of the section from every gate that
    passes a list over. Nor is it an item of a list (`_in_a_list`). A line in a listing, an
    HTML comment or the front matter opens none.

    The list ends at the next heading whatever its level, since the bold line has none to
    compare; at a line shaped like a heading that pandoc prints as text, where the audit's cut
    ends too, since running on past it would hide what follows; and at a paragraph that is
    no entry (`_ends_a_list`). A paper converted from Word has its other titles in bold as
    well, and journals ask for the figure legends and the tables after the references: run on
    to the next heading, the list hid them from G14. A heading that names the reference list,
    `# References`, is not found here; `Section.is_references` reads it."""
    headings = find_headings(text)
    newlines = [found.start() for found in re.finditer("\n", text)]
    offsets = [0, *(index + 1 for index in newlines)]

    def line_of(offset: int) -> int:
        return bisect_right(newlines, offset - 1)

    lines = scannable(text).split("\n")
    heading_lines = {line_of(heading.start) for heading in headings}
    breaks = heading_lines | heading_shaped(lines)
    # The line after a heading opens a paragraph; after a setext heading, the line after its
    # rule.
    under = {line_of(heading.start) + heading.setext for heading in headings}
    spans: list[tuple[int, int]] = []
    number = 0
    while number < len(lines):
        if (
            number in heading_lines
            or not _opens_a_paragraph(lines, number, under)
            or _in_a_list(lines, number)
            or not is_bibliography_heading(lines[number])
        ):
            number += 1
            continue
        start, number = number, number + 1
        while number < len(lines) and number not in breaks and not (
            _opens_a_paragraph(lines, number, under) and _ends_a_list(lines, number)
        ):
            number += 1
        spans.append((offsets[start], offsets[number] if number < len(lines) else len(text)))
    return spans


def _opens_a_paragraph(lines: list[str], number: int, under: set[int]) -> bool:
    """Whether line `number` opens a paragraph: it is the first, or the line above is blank or
    ends a heading (`under`)."""
    return not number or not lines[number - 1].strip() or number - 1 in under


#: A list item's marker: "3." or "3)" of an ordered list, "-", "*" or "+" of another.
_ITEM = re.compile(r"[ ]{0,3}(?:[0-9]{1,9}[.)]|[-*+])(?:[ \t]|$)")


def _in_a_list(lines: list[str], number: int) -> bool:
    """Whether line `number` is a list's: indented, as an item's second paragraph is, or an
    item with an item before it or after it. "3. References" after "2. Registries" in a list
    of sources searched is the list's third item, and "1. References" over "2. Registries"
    its first; "6. References" between paragraphs of the Discussion and of entries is the
    title of the reference list, numbered, and pandoc writes a numbered title paragraph of a
    Word document as `6\\. References`, which is no item."""
    line = lines[number]
    if line[:1] in (" ", "\t"):
        return True
    if not _ITEM.match(line):
        return False
    above = number - 1
    while above >= 0 and not lines[above].strip():
        above -= 1
    while above > 0 and lines[above - 1].strip():
        above -= 1
    below = number + 1
    while below < len(lines) and not lines[below].strip():
        below += 1
    return any(0 <= at < len(lines) and _ITEM.match(lines[at]) for at in (above, below))


#: A paragraph all in bold, a title in a paper converted from Word: "**Figure legends**",
#: "__Supplementary material__", "***Figure legends***", "**Table 2**:".
_BOLD = re.compile(r"[ ]{0,3}(\*\*|__)([*_]?)(?=\S)(?:(?!\1).)+?(?<=\S)\2\1[\s:.]*")
#: A paragraph that opens with a label in bold, "**Funding:** The work was ...".
_LABEL = re.compile(r"[ ]{0,3}(\*\*|__)(?=[^\s*_])[^*_\n]{1,80}?(?:\1[ \t]*:|:[ \t]*\1)")
#: A paragraph that is no entry of a reference list: a figure's, a table's, a box's or an
#: appendix's caption in each shape journals print, "Figure 1.", "Fig 1.", "FIGURE 1 |",
#: "S1 Table.", "Supplementary Table S1", "eTable 1", "Box 1", "Appendix A", "Additional
#: file 1"; a table, a pipe or a grid one; an image; a binding of a table or a figure. A
#: caption's number is needed, so that "Fig trees and ..." and an author named Box are
#: entries; an appendix's may be a letter, and a figure's or a table's a Roman numeral
#: ("TABLE I."), but not a box's: "Box I, Jenkins GM." is an entry.
_NO_ENTRY = re.compile(
    r"[ ]{0,3}(?:!\[|\||\+[-=]|\{\{|table:|[*_]{0,3}(?:"
    r"(?:supplementa(?:ry|l)\s+|online\s+|e)?(?:fig(?:ure)?s?\.?|tables?)\s*[ivx]+\b"
    r"|(?:supplementa(?:ry|l)\s+|online\s+|e)?(?:fig(?:ure)?s?\.?|tables?|box)\s*s?[0-9]"
    r"|(?:supplementa(?:ry|l)\s+|online\s+|e)?appendi(?:x|ces)\s*(?:[0-9]|[a-z]\b|[ivx]+\b)"
    r"|additional\s+files?\s*[0-9]"
    r"|s[0-9]+\s+(?:fig(?:ure)?|table|file|appendix|text|data(?:set)?|video|movie)\b))",
    re.IGNORECASE,
)
#: A pandoc simple table's rule under its header row, "  ------- -------", or the rule
#: that opens a multiline table or is a rule across the page.
_TABLE_RULE = re.compile(r"[ ]*-{2,}(?:[ ]+-{2,})+[ ]*")
_RULE = re.compile(r"[ ]{0,3}-{3,}[ ]*")
#: A title of back matter standing alone as a paragraph: a statement's
#: (`STATEMENT_NAMES`, "Funding", "Acknowledgements", "Data availability"), and "Figure
#: legends", "Tables" or "Supplementary material".
_BACK_MATTER = re.compile(
    rf"(?:[0-9]+\\?[.)]\s*)?(?:{STATEMENT_NAMES}"
    r"|(?:figure|table)s?(?:\s+(?:legends?|captions?|titles?))?"
    r"|supplementa(?:ry|l)\s+(?:materials?|information|data|files?)|appendi(?:x|ces))[\s:.]*",
    re.IGNORECASE,
)


def _ends_a_list(lines: list[str], number: int) -> bool:
    """Whether the paragraph that line `number` opens ends a reference list: one that is no
    entry (`_NO_ENTRY`), a table under a rule, a paragraph all in bold or opening with a bold
    label, or a title of back matter alone on its line. An entry that opens with "Table" or
    "Figure" and a number, which no style writes, would end it too, and the entries after it
    are then read as prose: a false alarm, where running on hides the paper. A blank line,
    one of several between entries, opens nothing."""
    if not lines[number].strip():
        return False
    if _NO_ENTRY.match(lines[number]) or _LABEL.match(lines[number]):
        return True
    paragraph = []
    for line in lines[number:]:
        if not line.strip():
            break
        paragraph.append(line)
    if _RULE.fullmatch(paragraph[0]) or (
        len(paragraph) > 1 and _TABLE_RULE.fullmatch(paragraph[1])
    ):
        return True
    joined = " ".join(line.strip() for line in paragraph)
    if _BOLD.fullmatch(joined):
        return True
    return (
        len(paragraph) == 1 and joined[:1].isupper() and bool(_BACK_MATTER.fullmatch(joined))
    )


def ends_a_list_alone(paragraph: str) -> bool:
    """Whether a paragraph written on one line, as each of a .docx's is read, ends a
    reference list under a line that is no heading, by the rules `_ends_a_list` holds a
    Markdown paragraph to. The audit ends a .docx's list there, as `check` ends one in
    Markdown. Bold is not in a .docx's text, so a title in bold ends it only where it is a
    back-matter title or a caption's shape."""
    return _ends_a_list([paragraph.strip()], 0)
