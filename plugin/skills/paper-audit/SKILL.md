---
name: paper-audit
description: Check the numbers in a paper that was not written with manuscript-guard against the analysis outputs, and report honestly what a match is worth. Use when handed an existing .docx, Markdown or LaTeX manuscript whose numbers were typed by hand, before resubmitting an old paper, or before moving one into a manuscript-guard project. Not for a manuscript-guard project, whose numbers are bound (use results-binding).
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

`--against` is the backing set, and it decides whether the audit tells you anything. It
may be left out when there are no outputs to hand: then no number is compared, the report
says so on its first line, and the checks that need no outputs still run (step 3). Say that
to the author in those words; never call such a report a check of the numbers.

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

Where a table reports means of whole numbers, a Likert-type scale or a count, ask the user
which rows they are and name them with `--whole-numbers "pain score" visits`: each mean in
those rows is held to its column's n, and one no whole total gives is listed. Never name a
row the paper does not describe as whole numbers; a mean of a continuous measure would be
listed as a misprint. A row whose means are of several items per person is read as one
number each, and a right mean can be listed: check those by hand against n times the items.

## 2. Run it

```bash
manuscript-guard audit manuscript.docx supplement.docx \
    --against results/ tables/ --figures figures/
```

It needs no project and reads no `paper.yaml`. A `.docx` is read with tracked changes
accepted and table cells kept apart, from the body, footnotes and endnotes; headers,
footers and comments are not read. Two paragraphs joined by deleting or moving the mark
between them are read as one, in the last one's style, as Word shows them once the change
is accepted. A join is not read across a table or a content control: Word runs a paragraph
into the first cell of a table after it, and the audit reads the two apart, so check by hand
the numbers either side of a deleted mark just before either. The
notes are read after the reference list has been cut from the body, so they are always
audited. Markdown and text files are read as written,
and `--` between digits is read as a separator and a minus in every format: `-0.72--0.30`
runs to -0.30, as it does in R's output. A Markdown paper that writes a range as
`2010--2019`, meaning pandoc's en dash, gets `-2019` reported as not found; check such
ranges by hand. A `.tex` is read with the files it inputs from its folder, at `.tex` lines;
in a folder every `.tex` with `\documentclass` starts a paper, an old draft or a LaTeX
template too, so name the paper's own file when the folder holds others; a file nothing
inputs is named under `Passed over`. There is no reader for a PDF
manuscript. `--figures` takes SVG and PDF files with a text layer; one with no text at all,
such as a matplotlib SVG with its labels drawn as outlines, is listed as unreadable rather
than audited. `--strict` exits 1 when a number is in no output, a paper, a figure or a
stretch of one could not be read, no number was read, the arithmetic of a table or a flow is
exactly wrong (a total off, categories over their column's n, a count held back that a
printed total gives away, a flow printed as a nested list that does not add up), or an
interval or a test of the Abstract differs from its one counterpart where the paper reports
in a single number, and the audit exits 2 when nothing given could be read at all,
`--minimum-cell-count` is below 1, or `--dry-run` or `--lookup-cache` is given without
`--lookup`. Ask the author for the data custodian's minimum and pass it as
`--minimum-cell-count N`; without it a count held back is taken to hide every count from 1
to its bound.
`--json` gives the report for a script, and on exit 2 an object whose `ok` is false, with
the reason.

G6 and G14 read the words as `check` does, a .docx through the conversion `init --from`
makes (skipped with a note without pandoc); ask the author which English the paper is in
and pass `--english british` or `american`. Neither is counted by `--strict`. The reference
list is counted and its numbered citations held to it; nothing is sent to a registry
unless you pass `--lookup`, and then ask the author first: run `--lookup --dry-run`, show
what would be sent (each DOI to Crossref and OpenAlex, and to DataCite and doi.org where
Crossref has no record; each PMID to PubMed), and keep the answers with `--lookup-cache DIR`
if they will audit again.

## 3. Read the report

What was read and what was not comes first, then a section for each check: `Membership`,
`Arithmetic`, `Abstract against Results`, `Small cells recoverable by subtraction`,
`Writing (G6) and Language (G14)`, `References (G7)`. Membership lists the
unmatched numbers by file, up to 40 per file and then only a count, followed
by `What a match is worth here`: the
share of integers 1–100, of integers 1–1000, and of two-decimal values that would match by
chance against this backing set, with a verdict. Arithmetic lists the numbers that do not
fit the ones beside them, a P and its statistic or an n (%) and its denominator, which
needs no outputs, and apart a table's total its counts do not add up to and a flow printed
as a nested list that does not add up, with notes on what it read as overlapping or did not
read. Abstract against Results lists each conflict, each number of the Abstract found
nowhere the paper reports, which may be a stale value or one the Results never give, and
those matched only as a rounding, and ends with its own chance-match rate; where it says
"not compared" the paper has no Abstract or no Results heading it could find. Small cells lists
each count held back ("<5") that a total gives away, with the count it can only be: a
disclosure to report to the author before the paper goes anywhere, never to work round. Report each section apart; a finding of G6 or G14 is about the words, and
no evidence about the numbers.

Two things about the list. `line N` is a line of the extracted text, which in a `.docx` is
a paragraph, not a page or a line in Word. The context shown is the first 140 characters of
that paragraph, so the number itself is often not in it. Find it before you report on it.

## 4. Triage what did not match

Each unmatched number is a stale or wrong value, a value from a source not in `--against`,
one written another way than the outputs write it, or vocabulary, an axis tick or a
reference entry. Only the first is what you are looking for. Before you report on any,
read [references/triage.md](references/triage.md): what to do with each kind, and where the
audit cuts a reference list, so that you can check the ranges it names under `Not audited`.

## 5. Say what a clean report does not mean

A match means the number appears somewhere in the outputs. It does not mean it appears in
the right place: a value correct in the abstract and wrong in the Results passes the
membership check, and the Abstract against Results finds it only where the two are an
interval or a test paired exactly; a number of the Abstract found in the Results may be
another quantity that happens to be printed the same. An
interval matches when both bounds appear anywhere, not necessarily together. Numbers the
classifier accepts as conventions or references are never compared at all, and that
includes `p < 0.05` anywhere in the text and the lines the report lists under
`Not audited`. Nor are numbers inside fenced code blocks in a Markdown paper. Conventions, and
numbers on lines taken for reference entries that happened to
match, are counted as "conventions or references"; the numbers on a cut reference list and
in fenced code are not counted at all. Describe all of them as not checked, never as
matched.

So report what was done, not a verdict: how many numbers were examined, how many matched,
what the chance-match rate was, and which unmatched ones you checked by hand and what you
found. Never tell the author the numbers were verified.

## 6. Moving the paper into a project

`import` refuses a `.docx` this toolkit did not build. For a paper still being written, the
route is:

1. `manuscript-guard init my-paper --from paper.docx`. It writes the paper as
   `manuscript/main.md`, each table as a pipe table where its cells hold only paragraphs, the
   pictures in `manuscript/media/`, and the title page in a comment at the top that no gate
   reads. Read what it prints: a table with a list or another table in a cell is left as a
   grid table, and a comment that holds the abstract hides its numbers until it is moved out.
   Do not convert with `pandoc paper.docx -t markdown`: it writes most Word tables as
   multiline tables, which `check` refuses at every stage. A paper written in LaTeX needs no
   conversion: `manuscript-guard init --latex`, then its files go in `manuscript/`, the
   entry file as `main.tex`, loading `mgvalues`.
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
