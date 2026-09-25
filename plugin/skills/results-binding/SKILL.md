---
name: results-binding
description: Publish values from the analysis through the Python or R emitter, write them into the manuscript as bindings, and get an unbound number out of the red. Use when writing or changing an analysis script in a manuscript-guard project, when putting a result, table or figure into the text, or when check reports unclassified-number, unresolved-binding, unquoted-result, hand-authored-table, results-edited, script-newer, input-changed or duplicate-quantity.
---

# Binding the numbers

The rule the whole toolkit rests on: **in manuscript source, a bare number is a defect
unless it is a recognised convention or a structural reference.** A number from the
analysis cannot be typed at all. It is published by the analysis and bound by name, so it
cannot go stale and cannot pass by coinciding with something.

That takes two halves: the analysis publishes, and the manuscript binds.

## 1. Publish from the analysis

Python:

```python
from manuscript_guard.emit import Emitter

em = Emitter(__file__, inputs=["data/cohort.csv"])     # inputs relative to the project root
em.value("cohort.n", len(rows))                        # an int displays as itself: 4000
em.value("cohort.n_exposed", n, display=f"{n:,}")      # when the journal wants 4,000
em.value("case.pct_serious", pct, digits=1)            # a float needs digits or display
em.value("model.p", p, display="<0.001")               # a comparator only has to hold
em.interval("ror", point, low, high, digits=2)         # ror.point, ror.ci_low, ror.ci_high
em.value("table2x2.a", a, quoted=False)                # published but not quoted in the text
em.write()                                             # results/<script stem>.json + .sha256
```

R, after `remotes::install_github("BasileChretien/manuscript-guard", subdir = "r/manuscriptguard")`
or `R CMD INSTALL` on the same directory of a clone:

```r
library(manuscriptguard)
em <- mg_emitter("analysis/02_model.R", inputs = "data/cohort.csv")  # run from the project root
em$value("model.n", 412L)
em$interval("model.or", 2.5, 1.8, 3.4, digits = 2)
em$write()
```

What the emitter holds you to:

- **Rounding is decided here, once.** `display` is fixed at emit time, so one quantity cannot
  be rounded two ways in two sections. There is no formatting option in the manuscript. If a
  coarser rounding is needed somewhere, emit a second key.
- Keys are lower case, dotted: `cohort.n_reports`. Table keys take no dots. A bad key is
  not caught when emitting; the whole fragment then fails the schema at `check`, and none of
  its values load.
- One namespace covers all scripts. A key published by two scripts is `duplicate-key`.
- Inputs are declared, and their digests recorded. Change the data and G1 says which
  results are stale.
- Units are not rendered. Write `{{results.case.pct_serious}}%` in the text.
- NumPy integers are refused; pass `int(x)`. Years and study periods are numbers like any
  other: emit them.
- An R string holding digits is not refused the way Python refuses it. Do not publish
  `"12.3 (95% CI 10.1 to 14.9)"` as one value; publish the three numbers.

**Never edit `results/`.** The fragments are machine-written and digested. An edited one is
`results-edited`, the plugin refuses the write, and `manuscript-guard verify` re-runs the
analysis in a scratch copy and compares value by value.

## 2. Bind in the manuscript

```markdown
The database held {{results.cohort.n_reports}} reports. The reporting odds ratio was
{{results.ror.point}} (95% CI {{results.ror.ci_low}} to {{results.ror.ci_high}}), and
{{results.case.pct_serious}}% of cases were serious [@smith2020Cohort].

{{table.baseline}}

{{figure.forest}}
```

- `{{results.…}}` resolves against `results/`; `{{lit.…}}` against `literature/ledger.yaml`
  and `attested.yaml` (the [literature-verify](../literature-verify/SKILL.md) skill).
- `{{table.key}}` goes on its own line and becomes the table with its caption.
  `{{figure.key}}` inserts `figures/<key>.<ext>`. Neither is numbered for you. A mistyped
  figure key passes `check` and fails at `build`; a mistyped table key is named only at
  `build`, though `check` reports the intended table as `unplaced-table`.
- Cross-references such as "Table 2" and "Figure 1" are accepted as structural and never
  checked against the real numbering. Number them by hand and look.
- Text inside HTML comments is ignored and never reaches the document. A number inside a
  fenced code block is judged as code, and a number in a string literal there is a claim.
- `manuscript/supplementary/` is checked the same way and built as its own document.

## 3. Tables and figures come from results

A pipe table typed with numbers in it is `hand-authored-table`. Emit it:

```python
em.table(
    "baseline",
    columns=["Characteristic", "Exposed", "Unexposed"],
    rows=[
        ["Reports", n_exp, n_unexp],
        ["Female", em.cell("{} ({})", f_exp, (100 * f_exp / n_exp, 1)),
                   em.cell("{} ({})", f_unexp, (100 * f_unexp / n_unexp, 1))],
    ],
    caption="Characteristics by exposure. Values are n (%) unless stated.",
)
```

A cell holding more than one number must be built with `em.cell`, which records its parts.
An f-string produces the same characters and none of the provenance, and is refused as
`typed-composite-cell`.

A figure script lives in `figures/`, reads the results, and types no data values. Numbers in
the rendered figure must be result displays, conventions, or declared ticks in
`figures/<name>.guard.yaml`, each with a `why`. With matplotlib, set
`rcParams["svg.fonttype"] = "none"` or the figure has no text to check. Reviewing the
rendered figure is the [figure-review](../figure-review/SKILL.md) skill.

## 4. Getting a number out of the red

```bash
manuscript-guard explain manuscript/main.md     # every number, and the rule that took it
manuscript-guard bind                           # each unbound number, and the ways out
```

There are four ways out, and usually it is the first:

1. It is already published and was typed instead of bound. `bind` names the key whose
   display matches. `bind --apply --only manuscript/main.md:42` applies the suggestions on
   line 42 only, and is refused if any number on that line has no single match; the path is
   relative to the project root. `bind --apply` alone takes every unambiguous
   match, and a match is a guess: "10 of them" can be bound to a ten-year study period.
   Where two keys display the same, `bind` refuses to choose, and so should you.
2. It should be published. Emit it from the analysis and bind it.
3. It comes from the literature. Ledger entry, with the quote and the stored source.
4. It is a convention of scientific writing, not a result. The shipped conventions
   cover things like `p < 0.05` in the Methods, `95% CI` and `per 1,000 person-years`. For
   a convention of your own field, add one to `paper.yaml` with a reason, pinned to the
   value rather than to a shape:

   ```yaml
   conventions:
     - pattern: '(?i)minor allele frequency (?:below|<) 1%'
       why: Standard genotype quality-control threshold, stated in the Methods.
       added_on: 2026-09-24
   ```

   A name that contains digits, such as a gene or a product code, goes under `terms:`.

   If `p < 0.05` is reported although it is in the Methods, look above it for a line that
   starts with `#`, or sits over a line of `-` or `=`, inside a paragraph, a list item or a
   quotation. Pandoc prints that line as text, not as a heading, and the gate ends the
   Methods there. Rewrap the line or put a blank line before it; do not add a convention.

   Every run reports how many numbers the project's own rules accounted for. A pattern
   wide enough to cover results is allowed, and it is visible, and it switches the check
   off.

**A value that matches is a suggestion, never evidence.** The gate never accepts a literal
because it matches a result. `bind` uses the match only to propose a binding, which is then
checked like any other.

## 5. The findings

| Code | Ask |
|---|---|
| `unclassified-number` | bind it, emit it, cite it, or declare the convention |
| `unresolved-binding` | the key does not exist; the finding suggests the nearest one |
| `unquoted-result` | a published value is quoted nowhere: quote it, or emit with `quoted=False` |
| `unplaced-table` | an emitted table is never placed with `{{table.key}}` |
| `hand-authored-table` | emit the table |
| `script-newer`, `input-changed` | re-run the script that wrote the results |
| `input-missing` | restore the input, or stop declaring it, then re-run |
| `results-edited`, `no-digest` | re-run through the emitter; never edit the fragment |
| `duplicate-quantity` | a warning: two quoted keys hold the same value. One quantity? Publish it once. A coincidence? Nothing to do |
| `divergent-display` | the same value is displayed two ways; pick one display |
| `declared-same-but-differs` | two keys declared one quantity with `same_as=` have drifted apart |
| `interval-reversed` | the text quotes the upper bound first; swap the two bindings |
| `estimate-outside-interval`, `interval-inverted` | fix the interval in the analysis, with `interval()` |

## If you are a model doing this

Never type a number the analysis produced, even one you can read straight off the results
file. Bind it. The check would catch the literal, and binding is the whole point.

Never run `bind --apply` without `--only` on a manuscript you did not just write. Read each
suggestion, and apply the ones whose meaning, not just value, is right.
