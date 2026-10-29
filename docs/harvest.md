# Harvesting an output, and a site's receipt

Some analyses will never call the emitter. A script written before the project, a colleague's
SAS program, a pipeline that writes `estimates.csv` and nothing else. `manuscript-guard
harvest` takes such an output in as results, so that the manuscript binds its numbers as it
binds emitted ones. It runs nothing, and `check` says so until something has. The commands
are listed in the [README](../README.md).

## `harvest.yaml`

Each output is an entry of `harvest.yaml`, at the project's root:

```yaml
entries:
  - key: cohort                  # results/cohort.json, table.cohort, cohort.<row>.<column>
    output: output/cohort.csv    # .csv, .tsv or .json, from the project's root
    script: analysis/cohort.R  # the script declared to write it
    inputs:                      # the data it read, as the emitter records them
      - path: data/extract.csv
        restricted: true
    row_key: group               # the column whose cells name the rows (optional)
    columns: [n, rate]           # the columns taken in (optional; all where absent)
    digits: {rate: 1}            # decimal places, for every column or by column (optional)
    counts: [n]                  # the columns whose cells are counts (optional)
    quoted: false                # the table is working output, not placed (optional)
    receipt: site-a              # the site that holds the data (optional; below)
```

`manuscript-guard harvest OUTPUT --script S --input I … --key K` adds an entry at the end of
the file, its comments kept, and harvests it; `--row-key`, `--columns`, `--digits`,
`--restricted`, `--synthetic`, `--counts`, `--not-quoted` and `--receipt` fill the rest. A plain `manuscript-guard
harvest` harvests every entry again, after the scripts have been run again.

## What is read

A `.csv` or `.tsv` with one header row, every row as wide as it; a JSON object of scalars,
read as the two columns `name` and `value`; or a JSON array of records, which needs
`row_key`. Anything else (a nested object, `true`, `NaN` or a number too large to be
finite, a ragged row, two rows or two columns whose names make one key) is refused, not
flattened by a guess. R's `write.csv` and pandas' `to_csv` write the row names under an empty
first header, which names no key: write the file without them (`row.names = FALSE`,
`index=False`). Leaving the column out with `columns` is no way round it at a site, whose
receipt reads every column of the file.

Each cell is a value, `<key>.<row>.<column>`, its row named by the row key's cell or by its
number from 1, and its column by its header, both in lower-case letters, digits and
underscores. Its display is the output's own text, unless `digits` is given:

| Cell | Value | Display |
|---|---|---|
| `120` | 120 | `120` |
| `1.50` | 1.5 | `1.50`, or `1.5` with `digits: 1` |
| `52.1%` | 52.1, unit `%` | `52.1%` |
| `1,234` | 1234 | `1,234` |
| `<5` | none: the count is held back | `<5` |
| `Women` | the text | `Women` |
| `12.3 (10.1 to 14.5)` | refused: one number to a cell | |

The values are written as intermediates (`quoted: false`), since an output has more cells
than a paper quotes, and the table, `{{table.cohort}}`, is placed like an emitted one: G2
fails `unplaced-table` until it is, unless the entry says `quoted: false`, for working
output.

`counts` names the columns whose cells count people or records. Only those are held to the
custodian's `minimum_cell_count` by G2, and a whole number in any other column (degrees of
freedom, a year) is no count. Without `counts`, every number with no unit that is whole is
one, "3" and "3.0" alike (an emitted value is a count only where it is an integer), so an
odds ratio printed "1.0" is a count of one: name the count columns. A count held back ("<2",
"≤4") is held by its bound, as the emitter's `display="<2"` is: below a minimum of 5, "<2"
still says the count is one. Text with a digit in a count column, or anywhere without
`counts`, is read as `deposit` reads a table cell: "2 (1.5%)" and "2/40" are 2, and a cell
from which no count can be read ("n=2", "12.3 (10.1 to 14.5)") is refused there; so is a
whole number with a unit other than "%" ("2 patients").

## What `check` says

G1 holds a harvested results file as it holds an emitted one: its inputs, its script and
its own digest. It also fails `harvested-output-changed` once the output is not the one
read, and `harvested-output-missing` once it is gone.

That the script writes the output is declared by `harvest.yaml`, and nothing here shows it.
So G1 warns `harvest-declared`, at every stage, and the reproducibility block of `check`
says "declared", until either of two things covers it:

- **`manuscript-guard verify`** runs the script in a scratch copy, the declared output
  deleted first, harvests what it wrote by the entry the results file records, and compares
  value by value. A script that writes no output is `rerun-failed`.
- **A site's receipt**, below.

## Data held at a site

Where the data custodian keeps the data at their site, the centre cannot run the analysis.
The site runs it, in its copy of the project:

```bash
manuscript-guard verify --receipt site-a
```

Each harvest entry with `receipt: site-a` is run in a scratch copy, and
`receipts/site-a.receipt.json` is written: when, the tool's version, the runner and its
version, the script by its path and digest, each input by its label (its path from the
project's root, never where it is on the site's disks) and digests, the lockfiles, each
output by its digest and size, and the exit code. The output the run wrote is put where the
entry declares it. Nothing is written where a run fails, writes no output, or writes one
holding a count below the custodian's `minimum_cell_count`, held back behind a bound
tighter than it, or in a cell from which no count can be read. The whole output file is
read, since the whole file leaves the site: a
column the entry does not take in is held as a count column, and with no `counts` every
column is. A count held back that a table's total row or header gives away by subtraction
is printed as a warning, as `deposit` prints it, and the receipt is written: a total read
from a label may be no sum, and a harvested output declares no sum that would make it
certain.

The site sends the outputs and the receipt; the data stay. At the centre, `harvest` takes the
output in only where it is the one the receipt covers, with the receipt's inputs and the
receipt's digest. G1 then fails `receipt-changed` where the receipt was edited or is gone,
`receipt-output-mismatch` where the output is not the receipt's, and `script-newer` where the
script changed since the site ran it; an input that is not at the centre is a note,
`input-at-site`. `verify` passes such a results file over ("data held at site-a; receipt of
2026-10-29"): it counts as not re-run, never as reproduced.

A receipt is not signed. It is the site's declaration of what ran, as an attestation is a
person's, and anyone who can write the file can write another. [DESIGN.md](../DESIGN.md),
"Known gaps", says what else it does not prove.
