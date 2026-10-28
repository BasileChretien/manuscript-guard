# Triage of the numbers an audit did not find

Part of the paper-audit skill, read when `manuscript-guard audit` lists numbers under
`NOT FOUND IN ANY OUTPUT` or under `NOT FOUND, ON LINES READ AS REFERENCE ENTRIES`, or when
its `Not audited` section names a range of lines to check.

## What each unmatched number can be

Each unmatched number is one of these, and only the first is what you are looking for:

| What it is | What to do |
|---|---|
| A stale or wrong value | Tell the author, with the value the outputs hold |
| From a source not in `--against` | Add the source, or check the number by hand |
| Rounded, a percentage written as a fraction, or `×10⁻ⁿ` | Check by hand against the output |
| A magnitude quoted without its sign, "fell by 0.51" for -0.51 | Check by hand. The sign is compared, so this is reported |
| A range written `2010--2019` in Markdown | Check by hand; `--` is read as a separator and a minus |
| `412.` opening a line of a Markdown or text paper, directly under a line of prose | Check it: a list cannot start under a paragraph, so it is a count a hard wrap moved, not numbering. (Under a list item's text it does start the next item, and is not reported.) A text file saved a paragraph per line with no blank lines reads as one paragraph, so its typed numbering lands here too |
| A label longer than three letters, `beta=0.4` | Check by hand |
| Vocabulary: `3-core`, an ISSN, a dose schedule | Check by hand |
| An axis tick | Nothing, if the axis is what it claims |
| A reference entry | See below |
| `41 200` read as `41` and `200` | A thousands separator written as a space; check by hand |

## Where the reference list is cut

A reference list starts at a line that is only a heading such as `References`,
`Reference list`, `Bibliography`, `Works cited` or `Literature cited`, perhaps with a number
(`5`, `5.`, `5)`), bold, or a trailing colon. A line the document marks as a heading (a
Markdown `#` or underline where pandoc prints a heading, a heading style in a `.docx`) needs
nothing more, and may end in a pandoc attribute block, as in `# References {-}`, `{.unnumbered}` or
`{#refs .unnumbered}`, which is dropped, as pandoc drops it; so are the closing `#`s of a
Markdown `#` heading. Most of what pandoc or Word prints is kept: braces pandoc does not
read as attributes, as in `# References {and further reading}` or `{title=" Works cited"}`,
a block with a no-break space after it, and every `#` of a setext heading or a Word
heading, as in `References #`. None of these starts a list. Two do, although pandoc or Word
prints their braces or `#`s: a `.docx` paragraph in a heading style typed as `References {-}`, and
an unpaired `*` or `_` before the block or the closing `#`s, as in `# *References {-}`.
The numbers under either go unread; DESIGN.md lists both under Known gaps.
Directly under a line of prose, a `#` line or an underlined one is printed as part of that
paragraph, so it marks nothing.
Any other line also has to be capitalised, not end in a full stop or in braces, and not
start with `#`: a wrapped "…duplicate / references." is not a heading, nor is
`References {-}` on a line of prose,
and neither is `# References` as a comment in a fenced R listing or typed into a Word
paragraph with no heading style. In Markdown, nothing in a fenced block, an HTML comment or
the front matter starts a list. A table cell
reading `References` is a column header, not a heading. The
list ends at the next heading: a Markdown heading (or a `#` or underlined line that pandoc
prints as prose, so an appendix written that way is not read as more references), or in a
`.docx` a paragraph styled as one.
Every such list is cut, and the report names the lines under `Not audited`. Check each
range. Code that is not fenced is not recognised as code, whether it is an unfenced or
indented listing in Markdown or a listing pasted into Word. A `References` line in it does
start a list, and in Markdown so does a `# References` comment that starts a block (after
a blank line, say), which pandoc prints as a heading. In a `.docx` whose headings are only
bold text, the list runs to the end of the body, and an appendix after it goes unread.

Only when there is no such heading is a line taken for a reference entry by its shape, and
only if it carries the year the way an entry does: "Smith, J. (2019).", "Fictional, Anne.
2021.", or the numbered styles' "Smith J, Jones K. … 2019;393:100-10.". A Harvard entry with
no full stop after "(2019)", or a book, web page or online-first article in a numbered
style, is not recognised, and its numbers show up as unmatched. A line taken for an entry is
still compared: numbers on it found nowhere are listed apart, under `NOT FOUND, ON LINES READ
AS REFERENCE ENTRIES`, which `--strict` does not count. Most are volumes and pages. Read the
list anyway, because a caption can have the same shape.
