# The data, held to the data dictionary

Where the project keeps `design/data_dictionary.yaml`, hand each table the analysis reads to
`check_data`, after any step that derives a variable the dictionary lists and before any
row is dropped:

```python
reports = pandas.read_csv("data/reports.csv")   # or csv.DictReader rows, or a dict of columns
reports["exposed"] = (reports["drug"] == "example-drug").astype(int)
men = (reports["sex"] == 1) & (reports["pregnant"] == 1)
flags = em.check_data(reports, computed={"no_pregnant_men": men.tolist()})
reports = reports.drop(reports.index[flags["age.out_of_range"]])   # rows, from nought
```

```r
reports <- read.csv("data/reports.csv")
men <- reports$sex %in% 1 & reports$pregnant %in% 1
flags <- em$check_data(reports, computed = list(no_pregnant_men = men))
reports <- reports[!flags[["age.out_of_range"]], ]   # TRUE where it counted the row
```

It runs the checks each entry asks for on the variables the table has a column for, and
publishes a count for each:

- `quality.rows`, the rows checked. A dictionary that lists datasets is checked one table
  at a time, `check_data(demo, dataset="demo")`, and the rows are `quality.rows.demo`.
- `quality.<variable>.missing` for every variable: blank, NA, or one of its `missing` codes,
  counted only where its `applies_if` holds. Then, where the entry asks: `wrong_type` (a
  number, a date or a time that is not one), `out_of_range`, `not_allowed` (a code it does
  not list; 1 and "1" are one code), `not_matching` (its `pattern`, matched whole),
  `outside_period` (a date outside `study_period`), `not_applicable` (a value where
  `applies_if` says the variable does not apply). A name in capitals or with dots is
  written in lower case with underscores: `BEN_SEX_COD` gives `quality.ben_sex_cod.missing`.
- `quality.rule.<rule>`, the rows that break each rule. An `order` or a `unique` rule over
  variables of this table is checked here. A `computed: true` rule is checked by your code,
  which passes one true or false for each row.

Counts only: nothing from a row is written. None of them has to be quoted; bind the ones the
Methods report (the [methods-writer](../../methods-writer/SKILL.md) skill). A count from one to
below the custodian's minimum (`custodian.minimum_cell_count` in `paper.yaml`) is printed
`<5`, which the Methods can bind and G2 passes. A table is checked once in the whole
project, since a key has one owner: check it as it was read, and say what was dropped
after. A variable a later script derives, on a table of its own, goes in a dataset of its
own in the dictionary, and that script checks it there: `check_data(analysis,
dataset="analysis")`. The dictionary is an input of the run, so editing it makes the counts
`input-changed` until the script runs again. One that does not read is refused with its
lines, as `check` refuses it. In R, `check_data` needs the yaml package.
