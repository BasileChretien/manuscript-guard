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

**It reads `.json .csv .tsv .txt .yaml .yml .md`, and skips everything else in silence**,
including `.xlsx`, `.rds`, `.log` and `.html`, any `.json` that does not parse (JSON
Lines saved as `.json` among them), and paths that do not exist. Save every backing file as
UTF-8 without a byte-order mark. Anything else (UTF-16, which Windows PowerShell 5 writes
by default, or a BOM, which its `-Encoding UTF8` adds) is skipped, misread as single
digits, or stops the audit, depending on the file type and the Python version.
Export spreadsheets to CSV first. Then read the first line of the report: `against 0
distinct numbers from 0 output file(s)` means no supported file was read, whether from a
typo, an empty folder or a folder of unsupported files. It never means a clean paper.

Keep it narrow. A directory is read recursively, READMEs and notes included, and every
extra number raises the chance of a coincidental match.

## 2. Run it

```bash
manuscript-guard audit manuscript.docx supplement.docx \
    --against results/ tables/ --figures figures/
```

It needs no project and reads no `paper.yaml`. A `.docx` is read with tracked changes
accepted and table cells kept apart, from the body, footnotes and endnotes; headers,
footers and comments are not read. The notes are read after the body, so a references
heading in the body cuts them off along with the bibliography (section 4). Markdown and text files are read as they are. There is
no reader for a PDF manuscript. `--figures` takes SVG and PDF files with a text layer.
`--strict` exits 1 when anything is unmatched.

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
| **Negative** | Check by hand. The outputs lose the sign when read, so a negative number never matches |
| A label longer than three letters, `beta=0.4` | Check by hand |
| Vocabulary: `3-core`, an ISSN, a dose schedule | Check by hand |
| An axis tick | Nothing, if the axis is what it claims |
| A reference entry | See below |
| `41 200` read as `41` and `200` | A thousands separator written as a space; check by hand |

The bibliography is dropped from the first line that reads `References`, `Bibliography`,
`Works cited` or `Literature cited`, with or without a leading `#`, a number such as `5.` or
`5)`, or a trailing colon. `Reference list`, `5 References` and a bold `**References**`
paragraph are not recognised. Everything after that line goes, and in a `.docx` that
includes every footnote and endnote, which are read after the body. Adding a recognised
heading to a copy of the document saves reading past forty spurious findings, at the price
of the notes: check those by hand.

With or without a heading, every line is also tested by its shape: a capitalised word, a
comma, another capitalised word, and within about 200 characters four digits from 1900 to
2099 standing alone (a year, `2019a`, or the decimals of `0.2013`). A line that fits counts as a reference entry. That catches author-year entries
and misses Vancouver ones (`Smith J, …`), whose volume and page numbers are then reported.
**It also catches body text.** In a `.docx` a line is a paragraph; in Markdown or text it is
a physical line, so a wrapped line in mid-paragraph counts too. "Overall, Japanese patients
accounted for 412 of 1985 cases" is treated as a reference, and none of its numbers is
compared, without a word in the report.

## 5. Say what a clean report does not mean

A match means the number appears somewhere in the outputs. It does not mean it appears in
the right place: a value correct in the abstract and wrong in the Results passes. An
interval matches when both bounds appear anywhere, not necessarily together. Numbers the
classifier accepts as conventions or references are never compared at all, and that
includes `p < 0.05` anywhere in the text, everything after the references heading
(appendices, and a `.docx`'s footnotes and endnotes), and any line shaped like a reference
entry (section 4). Read every line, every paragraph in a `.docx`, that opens with a word, a
comma and a capitalised word yourself.

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
