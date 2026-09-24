---
name: paper-audit
description: Check the numbers in a paper that was not written with manuscript-guard against the analysis outputs, and report honestly what a match is worth. Use when handed an existing .docx or Markdown manuscript whose numbers were typed by hand, before resubmitting an old paper, or before moving one into a manuscript-guard project.
---

# Auditing a paper that was written by hand

In a manuscript-guard project a number from the analysis cannot be typed at all, so nothing
passes by coincidence. A paper written the ordinary way has no bindings. Every number is a
literal, and the only question left to ask is a weak one: does this number appear
somewhere in the outputs?

`manuscript-guard audit` asks that question and then measures how little the answer means
for this particular paper. The measurement is not a footnote. In the project this toolkit
grew out of, the same question was asked with the analysis outputs as the backing set:
every integer up to 100 matched by chance, and of fifteen deliberately corrupted headline numbers it caught
none while reporting success.

## 1. Choose what to check against

`--against` is the backing set, and it decides whether the audit tells you anything.

**Use the analysis outputs as printed, not the raw data.** On the worked example, audited
against its results, 24% of the integers from 1 to 100 match by chance. Audited against
the row-level data, 100% do, and at the same time every odds ratio and percentage is
reported missing, because raw rows contain no derived statistics. Raw data therefore fails
twice: every count passes and every estimate fails.

**Match what the paper prints.** Separators, a trailing `%` and trailing zeros are removed,
and non-integers are compared to 10 decimal places. `3.84` in the paper does not match
`3.843972469205093` in a log,
and `36.4%` does not match `0.364`. Point it at rounded tables and formatted output where
they exist.

**Include every source of quoted values.** Literature values, numbers from a collaborator's
analysis, figures taken from a protocol: anything not in `--against` comes back unmatched.

**It reads `.json .csv .tsv .txt .yaml .yml .md`.** Anything else, such as `.xlsx`, `.rds`,
`.log` or `.html`, is listed in the report under `Outputs not read as given`, and so is a
`.json` that does not parse (JSON Lines saved as `.json`, say), which is then read as plain
text. A path that does not exist stops the audit with exit 2, and so does a set of outputs
with nothing readable in it. A byte-order mark names the encoding, so UTF-8 with a BOM and
UTF-16 (Windows PowerShell 5's default for `>` and `Out-File`) are read correctly; a file
with NUL bytes and no BOM is listed as not read. Export spreadsheets to CSV first, and read
that section of the report before the findings: every number in an output it names is
reported missing from the paper.

Keep it narrow. A directory is read recursively, READMEs and notes included, and every
extra number raises the chance of a coincidental match.

## 2. Run it

```bash
manuscript-guard audit manuscript.docx supplement.docx \
    --against results/ tables/ --figures figures/
```

It needs no project and reads no `paper.yaml`. A `.docx` is read with tracked changes
accepted and table cells kept apart, from the body, footnotes and endnotes; headers,
footers and comments are not read. One tracked change is not accepted: two paragraphs
joined by deleting or moving the mark between them are still read as two, so check by hand
the numbers either side of such a join. The notes are read after the reference list has been
cut from the body, so they are always audited. Markdown and text files are read as written,
and `--` between digits is read as a separator and a minus in every format: `-0.72--0.30`
runs to -0.30, as it does in R's output. A Markdown paper that writes a range as
`2010--2019`, meaning pandoc's en dash, gets `-2019` reported as not found; check such
ranges by hand. There is no reader for a PDF
manuscript. `--figures` takes SVG and PDF files with a text layer; one with no text at all,
such as a matplotlib SVG with its labels drawn as outlines, is listed as unreadable rather
than audited. `--strict` exits 1 when anything is unmatched or a paper or figure could not
be read, and the audit exits 2 when nothing given could be read at all.

## 3. Read the report

It lists the unmatched numbers by file, up to 40 per file and then only a count, followed
by `What a match is worth here`: the
share of integers 1–100, of integers 1–1000, and of two-decimal values that would match by
chance against this backing set, with a verdict.

Two things about the list. `line N` is a line of the extracted text, which in a `.docx` is
a paragraph, not a page or a line in Word. The context shown is the first 140 characters of
that paragraph, so the number itself is often not in it. Find it before you report on it.

## 4. Triage what did not match

Each unmatched number is one of these, and only the first is what you are looking for:

| What it is | What to do |
|---|---|
| A stale or wrong value | Tell the author, with the value the outputs hold |
| From a source not in `--against` | Add the source, or check the number by hand |
| Rounded, a percentage written as a fraction, or `×10⁻ⁿ` | Check by hand against the output |
| A magnitude quoted without its sign, "fell by 0.51" for -0.51 | Check by hand. The sign is compared, so this is reported |
| A range written `2010--2019` in Markdown | Check by hand; `--` is read as a separator and a minus |
| A label longer than three letters, `beta=0.4` | Check by hand |
| Vocabulary: `3-core`, an ISSN, a dose schedule | Check by hand |
| An axis tick | Nothing, if the axis is what it claims |
| A reference entry | See below |
| `41 200` read as `41` and `200` | A thousands separator written as a space; check by hand |

A reference list starts at a line that is only a heading such as `References`,
`Reference list`, `Bibliography`, `Works cited` or `Literature cited`, perhaps with a number
(`5`, `5.`, `5)`), bold, or a trailing colon. A line the document marks as a heading (a
Markdown `#` or underline, a heading style in a `.docx`) needs nothing more. Any other line
also has to be capitalised, not end in a full stop, and not start with `#`: a wrapped
"…duplicate / references." is not a heading, and neither is `# References` as a comment in
a fenced R listing or typed into a Word paragraph with no heading style. In Markdown,
nothing in a fenced block, an HTML comment or the front matter starts a list. A table cell
reading `References` is a column header, not a heading. The
list ends at the next heading: a Markdown heading, or in a `.docx` a paragraph styled as one.
Every such list is cut, and the report names the lines under `Not audited`. Check each
range. Code that is not fenced is not recognised as code, whether it is an unfenced or
indented listing in Markdown or a listing pasted into Word. A `References` line in it does
start a list, and in Markdown so does a `# References` comment at the start of a line,
which pandoc prints as a heading. In a `.docx` whose headings are only bold text, the list
runs to the end of the body, and an appendix after it goes unread.

Only when there is no such heading is a line taken for a reference entry by its shape, and
only if it carries the year the way an entry does: "Smith, J. (2019).", "Fictional, Anne.
2021.", or the numbered styles' "Smith J, Jones K. … 2019;393:100-10.". A Harvard entry with
no full stop after "(2019)", or a book, web page or online-first article in a numbered
style, is not recognised, and its numbers show up as unmatched. A line taken for an entry is
still compared: numbers on it found nowhere are listed apart, under `NOT FOUND, ON LINES READ
AS REFERENCE ENTRIES`, which `--strict` does not count. Most are volumes and pages. Read the
list anyway, because a caption can have the same shape.

## 5. Say what a clean report does not mean

A match means the number appears somewhere in the outputs. It does not mean it appears in
the right place: a value correct in the abstract and wrong in the Results passes. An
interval matches when both bounds appear anywhere, not necessarily together. Numbers the
classifier accepts as conventions or references are never compared at all, and that
includes `p < 0.05` anywhere in the text and the lines the report lists under
`Not audited`. Conventions, and numbers on lines taken for reference entries that happened to
match, are counted as "conventions or references"; the numbers on a cut reference list are
not counted at all. Describe all of them as not checked, never as matched.

So report what was done, not a verdict: how many numbers were examined, how many matched,
what the chance-match rate was, and which unmatched ones you checked by hand and what you
found. Never tell the author the numbers were verified.

## 6. Moving the paper into a project

There is no converter. `import` refuses a `.docx` this toolkit did not build. For a paper
still being written, the route is:

1. `manuscript-guard init`, then convert the text into `manuscript/*.md`, for example with
   `pandoc paper.docx -t markdown -o manuscript/main.md`.
2. Make the analysis publish its values. The [results-binding](../results-binding/SKILL.md)
   skill covers the emitters.
3. `manuscript-guard bind` lists every unbound number and proposes a key wherever exactly
   one published value displays the same. A proposal is a coincidence of value, and a paper
   converted from Word is full of coincidences, so read each one and apply only the right
   ones with `bind --apply --only manuscript/main.md:<line>`. Never run `bind --apply` alone
   here: a wrong binding passes every gate afterwards.

## If you are a model doing this

The pull is to summarise a mostly matched report as "the numbers check out". It does not
show that, and the report says so at the bottom for a reason. Quote the chance-match rate
whenever you mention a match.

Do not edit the author's paper to agree with the outputs. An unmatched number is a question,
and sometimes the output is the thing that is wrong. Show each mismatch and let the author
decide.
