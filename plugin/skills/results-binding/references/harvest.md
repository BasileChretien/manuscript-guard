# An output a script writes without the emitter

Part of the results-binding skill, read when an analysis writes its estimates to a CSV, a
TSV or a JSON file and will not call the emitter, or when `check` reports
`harvest-declared`, `harvested-output-changed`, `harvested-output-missing`,
`receipt-changed`, `receipt-output-mismatch` or `input-at-site`.

Prefer the emitter where the script can be changed: it records each value where it is
computed. Where it cannot, add the output to `harvest.yaml` and harvest it:

```bash
manuscript-guard harvest output/cohort.csv --script analysis/cohort.R \
  --input data/extract.csv --restricted --key cohort --row-key group
```

The values are `{{results.cohort.<row>.<column>}}` and the table `{{table.cohort}}`. A cell
that is not one number or plain text is refused: write each number to a column of its own.
List the columns that count people or records with `--counts`, so that the custodian's
minimum is held to them and to nothing else, and give `--not-quoted` for working output.

- **`harvest-declared`** (a warning at every stage): nothing has run the script. Run
  `manuscript-guard verify`, which runs it in a copy and reads the output it writes. Do not
  try to make the warning go away any other way.
- **`harvested-output-changed`**, **`harvested-output-missing`**: run the script, then
  `manuscript-guard harvest` again. Never edit the output or `results/`.
- **Data held at a site.** The site runs `manuscript-guard verify --receipt SITE` and sends
  the outputs and the receipt it writes; you harvest them. `receipt-changed`,
  `receipt-output-mismatch` and `script-newer` after a receipt are the site's to answer with
  a new run: ask the author to ask them. Never write or edit a receipt; it is the site's
  declaration, and it is not signed.
