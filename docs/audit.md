# Auditing a paper you already wrote

For a manuscript that was never built this way — no bindings, every number a literal —
there is one command:

```bash
manuscript-guard audit manuscript.docx supplement1.docx \
    --against results/ analysis_output.csv \
    --figures figures/
```

It reads a .docx, a Markdown or text file, and a LaTeX paper. A `.tex` named is read with
the files it inputs, from its own folder, as `check` reads a project's `main.tex`: its
numbers where they print, at the `.tex` line they stand on, and its tables cell by cell. In
a folder, every `.tex` with `\documentclass` starts a paper, and is audited as one: so is an
old draft, a cover letter or a template written in LaTeX, so name the paper's own file to
audit it alone. A file no paper inputs is named under "Passed over" and not read, and so is
a file a class or a package inputs. A `thebibliography` is cut as a reference list is, and a
stretch the LaTeX reader refuses in a file the paper reads is named under "Could not read",
which `--strict` counts.

`--against` may be left out. Then no number is compared with the analysis, the report says
so on its first line, "No outputs given: no number was compared with the analysis", and what
needs no outputs is read all the same: the numbers against each other, the words and the
reference list. The audit exits 2 when it did not happen: a path that is not there, a
folder with no paper in it, papers none of which could be read, outputs named in `--against`
none of which could, `--minimum-cell-count` below 1, or `--dry-run` or `--lookup-cache`
given without `--lookup`. With
`--json` it then prints `{"ok": false, "error": ...}`, with the reason, as well as saying it
on stderr.

The report comes in sections, after what was read and what was not:

| Section | What it holds | Counted by `--strict` |
|---|---|---|
| Membership | each number against the outputs, and what a match is worth there | a number in no output |
| Arithmetic | a table's totals and the counts they total, a characteristic's categories and their column's n; a P and its statistic, an estimate and its interval, an n (%) and its denominator, a mean of whole numbers and its n | a total off, categories over their n |
| Small cells recoverable by subtraction | each count held back ("<5") that a total beside it gives away, with the count it can only be | one a printed total gives away |
| Writing (G6) and Language (G14) | what `check` says of the words, on a project made for the paper | no |
| References (G7) | the reference list counted, its numbered citations held to it, and with `--lookup` what the registries say | no |

`--strict` also counts a paper, a figure or a stretch of one that could not be read, and an
audit that read no number. Of the arithmetic it counts what is exact, and nothing that rests
on reading a sentence or rounding (the author, 2026-10-28). `--json` prints the report in the shape `check --json` gives,
each finding with its section and whether `--strict` counts it; `ok` is what `--strict`
would say.

**The words.** G6 and G14 read a project's manuscript, so the paper is put into one made for
it in a temporary folder and the two gates run as `check` runs them. A .docx goes through
the conversion `init --from` makes, so its lines are lines of that converted text; without
pandoc a .docx is not converted, and the report says G6 and G14 were not run on it.
`--english british` or `american` declares the paper's English, which G14 holds its spelling
to; without it G14 holds the paper to the English most of its words are in.
`--submission-residue` makes a residue of the revision that answers a reviewer a failure, as
`check` does at the submission stage. Neither gate is counted by `--strict`.

**The references.** The list cut from the text is counted: its entries, and the DOIs and
PMIDs typed in them. Where the entries carry their numbers, "1." or "[1]", each bracketed
citation of numbers in the text, `[3]`, `[3, 5]` or `[3-5]`, is held to the list: a number
the list does not hold is reported, and so is an entry no citation names. A Markdown list is
numbered as pandoc prints it, from its first number up, so a list typed "1." on every entry
is 1, 2, 3; a number pandoc escaped, `1\.`, is printed as typed. A list Word numbers itself
prints no number, so in a .docx an entry's number is its place in Word's count, where Word
numbers every entry 1, 2, 3 in one count that starts at the list; a bracketed number in the
text does not make an unnumbered list a numbered one. A bracket after a value that encloses
it, `64 [55-72]`, is an interval and no citation. In LaTeX each `\cite` key is held to the
`\bibitem`s, and an entry is reported in the file that holds it. Nothing is sent anywhere
unless you ask: `--lookup` asks Crossref and OpenAlex about each DOI, DataCite about one
Crossref has no record of and doi.org about one DataCite has none of either, and PubMed
about each PMID. It reports a work retracted, withdrawn, under an expression of concern or
published since, a DOI or a PMID no registry has, and a registry that did not answer, as G7
does in a project. Only where no registry reported anything of any entry does it say how many
entries were asked and how many a registry knew; an entry answered from the records kept
counts as asked.
`--lookup --dry-run` lists what would be sent and sends nothing; `--lookup-cache DIR` keeps
each answer in `DIR` and reads it from there the next time. Without `--lookup-cache` nothing
is kept.

It reads the .docx with **tracked changes accepted** and **table cells kept apart** (Word
stores a row with no separator, so a naive read turns `39 | 20 | 26 | 16` into the single
number 39,202,616 and silently skips every table), drops the bibliography, classifies
conventions and cross-references, and reports every remaining number that appears nowhere
in your outputs.

The bibliography is found by its title in English, Spanish, Portuguese, French, German,
Italian, Turkish and Indonesian ("References", "Referencias", "Kaynakça", "Daftar pustaka"
and the like), and otherwise by the shape of its entries: journal articles in the numbered
and author-year styles, the BMJ's with no full stop before the year, books, chapters, web
pages and articles online first. A shape can be wrong, so the numbers on a line it accepts
are still compared, and those not found are listed apart. A title that is a plain paragraph
of a .docx, with no heading style, ends its list where `check` ends one under no heading: at
a figure's or a table's caption, a title such as "Funding" or "Figure legends" standing
alone, or a table. A .docx and a figure print `<!--` as typed, so nothing between it and
`-->` is hidden there. Numbers in names are classified as
`check` classifies them: an e-mail address is no number, nor a name the shipped terms hold,
such as "IL-4" or "interleukin-4". A Word 97-2003 document (.doc) is not read; save it as
.docx first. A .doc in a folder you give is named in the report as passed over, and does not
fail `--strict`.

**It also tells you how little that means.** The report ends with a measurement of the
backing set you supplied:

```
What a match is worth here:
  integers 1-100      100% of all possible values already match
  integers 1-1000     100%
  two-decimal           2%
  A match on a small integer means almost nothing here. Check those by hand.
  Point --against at the analysis outputs rather than the raw data if you can.
```

That measurement is the point. This audit can only ask whether a number appears *somewhere*
in the outputs, and in a previous project that question was measured as near-vacuous: 100%
of integers up to 100 already matched, and of fifteen deliberately corrupted headline
numbers it caught none. A clean audit report is not a clean paper, and the report says so
every time. Use `--strict` to exit non-zero on anything unmatched.

One check needs no outputs. Each t, F, chi-squared or z statistic with a P after it in
its sentence is held to that P: the P the statistic gives is worked out over every value
their printed digits allow, and a P that does not follow is listed apart, with whether it
falls on the other side of 0.05. A one-sided, adjusted or exact test the sentence names
is not judged, and `--strict` does not count these. A middle dot for the point, "0·62", is
read as one; a number written with a comma for its point, "0,62", is not read, so such a
paper has none of its tests judged. Each named estimate with a confidence
interval after it is held to it the same way: an estimate outside its own interval, a
ratio whose interval is lopsided on the log scale, and an interval that excludes its null beside a P above one less its level, or
includes it beside one below, are listed with them.

A table's n (%) is held to the denominator the table names for it, the count's own
("12/40 (30.0)") or the "n = 1200" of its column's header: 300 of 1200 is 25.0%, and a table
that prints 300 (26.0) is listed, with the denominators 26.0% of 300 would fit. Half a unit
in the share's last printed place is allowed. Only a column of shares is read: a "%" in the
cell, or "n (%)" in the row's label, the label over its rows or the column's header, says
so, or the shares of a characteristic's categories add up to 100. A row that names a mean,
a median, an SD, an IQR or a range is never read, nor a whole number up to 100 with no "%"
in a row whose label ends on a unit in percent ("Oxygen saturation, %"). A share of its row's own total, where the row's shares add
up to 100, and a share of its categories' own total, where they do, are not listed: a
subtype of another row, or a share of those with data. A row whose label carries a footnote
marker is listed as uncertain, since a note may give it another denominator. Pipe tables are
read in Markdown, and every table in a .docx.

**Totals.** A row labelled Total, All or Overall, in any case and with nothing after the
word but an n ("Total (n = 1,200)"), an "n (%)", footnote marks and punctuation, totals the
counts of the rows above it, back to the last row with no count in it, a characteristic's
own label, or the last total row; a column so headed totals the counts of the columns before
it, back to the last total column or the column of labels. "Total cholesterol", "Overall
survival" and "All other drugs" are no totals. A count is a whole number, "1,200", or the
count of an n (%) read as one; a cell held back, "<5" or "≤4", is every count from 0 to the
largest its bound allows. A line with a cell in it that is no count (a dash, an empty cell,
a mean and its SD) is not read, nor a column headed by a P, a ratio, a mean or a "%" with no
n. A total its counts do not add up to is listed, `sum-off`, with what they add up to.
Where a characteristic's categories have shares that add up to 100 and counts that add up to
more than the n of their column's header, that is listed too, `over-header-n`; fewer is what
missing data look like, and is not said.

**Small cells recoverable by subtraction.** A count printed "<5" because the data custodian
forbids printing it is printed all the same where a total and the other counts beside it
are: the total less the others is the count. Each line, a total and its counts, is read for
the range each count held back can be, the total less the others' highest up to the total
less their lowest, within its own bound; where that is one count it is listed with that
count. `--minimum-cell-count N` gives the custodian's minimum: a count of N or more given
away is not listed. Without it, any count from 1 is: the cell held back says it hides what
it holds. A count only a column's header n gives away is listed apart and not counted, since
the n is the categories' total only where none of the column lacks the characteristic.
Each line is read on its own: a count that only a row and a column together give away is not
found.

A mean of whole numbers, answers on a Likert-type scale or a count, is a whole total over
its n, so not every mean can be printed for it: 28 answers average 3.46 or 3.50, never 3.47
(the granularity test of Brown and Heathers, 2017). Nothing in a paper says its numbers are
whole, so this is read only in the rows you name. `--whole-numbers "pain score" visits`
reads each table row whose label holds one of those, at word edges and in any case, and
holds each mean in it (alone, with its SD in brackets, or with ± and its SD) to the n of
its column's header. A mean that no whole total over n gives is listed with the other
disagreements, with the totals either side and the n it would fit, since a mean of those
with data has a smaller n than its column. A mean for whose n every mean printed to its
places is possible is listed apart as not assessable: so for 100 numbers or more at two
places, and for 80 and 96. A label under which no mean was read is said. A row whose label
carries a footnote marker or an n of its own is uncertain. Means in sentences are not read.
A mean of several items per person is read as a mean of one number each, so a mean that is
right for its items can be listed: name only rows of one number per person, or quote the
value in the literature ledger, which takes both (`mean_of_whole_numbers: {n: 28, items:
3}`).

For a paper still being written, bind the numbers instead — then a stale one is impossible
rather than merely searched for.

## Bringing a Word paper into a project

```bash
manuscript-guard init my-paper --from paper.docx
```

This makes a project whose manuscript is the paper, read by pandoc with tracked changes
accepted, and prints what it did. Converting with `pandoc paper.docx -t markdown` instead
writes most Word tables as multiline tables, whose lines of dashes `check` refuses at every
stage; on fifteen real papers it did so for seven. `init --from` changes three things:

- **Tables.** A table whose cells hold only paragraphs is written as a pipe table. A cell's
  paragraphs and line breaks are joined with spaces, a merged cell's text stands in its
  first row and column with the cells it covered left empty, and a second header row or a
  footer row becomes a row of the body. A table with a list, another table or a block of
  code in a cell is written as a grid table and named in what `init` prints: `check` reads
  its rows, and the audit does not read its cells.
- **Pictures** are saved in `manuscript/media/`, and each image points there.
- **The title page**, what stands before the first heading, is set aside in one HTML
  comment at the top of `main.md`, where it is kept and no gate reads it. Only up to 600
  words: a longer run is taken for the paper's own text, an introduction with no heading
  over it, and stays where it is. A paper with no paragraph in a heading style has nothing
  set aside, and its bold-text headings are no sections to any gate.

What Word's Title, Author, Date and Abstract styles hold is what pandoc reads as the
document's metadata. The title goes to `paper.yaml` unless `--title` gives another, each
name of an Author paragraph to `authors.yaml` as the paper writes it, for you to split into
given and family name, and the abstract becomes the section `# Abstract`. pandoc reads the
Abstract style only straight after the Title, Author and Date paragraphs, so a paragraph in
that style elsewhere on the title page is found by reading the document again with its
styles, and joins the section where that reading matches the first. An Author
paragraph holding several names, a comma, a number or a superscript, and the date, go into
the comment. So does the Title paragraph, as well as `paper.yaml`'s plain title, where it
holds a note, a superscript, a link or a picture: a note on the title often names the funder
or the corresponding author. Nothing is guessed from how a line looks, so names typed in capitals on the
title page stay in the comment. Read it: an abstract there in no Abstract style hides its
numbers from every gate until you move it out.

A `.doc` is refused: open it in Word and save it as `.docx`. `--from` makes nothing where
`manuscript/` already holds a manuscript or the folder already has a `paper.yaml` or an
`authors.yaml`, and is refused with `--latex`.

[Back to the README](../README.md)
