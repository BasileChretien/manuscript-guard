---
name: results-binding
description: Publish values from the analysis through the Python or R emitter, write them into the manuscript as bindings, and get an unbound number out of the red. Use when writing or changing an analysis script in a manuscript-guard project, when putting a result, table or figure into the text, or when check reports unclassified-number, unresolved-binding, value-splits-paragraph, unquoted-result, typed-parameter, typed-software-version, typed-dictionary-release, parameter-unread, hand-authored-table, results-edited, script-newer, input-changed, duplicate-quantity, pointer-to-nothing, display-not-cited, cited-out-of-order, pointer-word-mismatch, ref-number-unknown, caption-names-another, quality-not-run, entry-unchecked or rule-unchecked. Not for prose style (use manuscript-writing), the Methods against the code (use methods-writer), or a paper written outside manuscript-guard (use paper-audit).
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

em = Emitter(__file__, inputs=["data/cohort.csv"], ci_level="95%")  # every interval's level
em.value("cohort.n", len(rows))                        # an int displays as itself: 4000
em.value("cohort.n_exposed", n, display=f"{n:,}")      # when the journal wants 4,000
em.value("case.pct_serious", pct, digits=1)            # a float needs digits or display
em.value("model.p", p, display="<0.001")               # a comparator only has to hold
em.interval("ror", point, low, high, digits=2)         # ror.point, ror.ci_low, ror.ci_high
em.value("ror.p", p, digits=3, of="ror.point", family="secondary")  # a p value names its estimate
em.value("female.pct", pct, digits=1, of="female.n", over="cohort.n")  # a share, its counts
em.value("age.sd", sd, digits=1, spread="sd", of="age.mean")  # a standard deviation, of what
em.correction("secondary", "holm")                     # how the family is corrected; "none" + reason
em.value("table2x2.a", a, quoted=False)                # published but not quoted in the text
alpha = em.parameter("alpha", 0.05)                    # param.alpha: a choice, handed back to use
em.software("statsmodels")                             # software.statsmodels, as imported
em.dataset("vigibase", "data/vb.csv", extracted="2024-03-01",  # dataset.vigibase.extracted,
           covers=(None, "2023-12-31"), fingerprint="3f9a1c2b7e4d5a60")  # .covers_to
em.variable("age_group", "categorical", label="age group", reference="18-44")
em.model("adjusted", fit, name="Adjusted model")       # model.adjusted.*, table.model_adjusted
em.write()                                             # results/<script stem>.json + .sha256
```

R, after `remotes::install_github("BasileChretien/manuscript-guard", subdir = "r/manuscriptguard")`
or `R CMD INSTALL` on the same directory of a clone:

```r
library(manuscriptguard)
em <- mg_emitter("analysis/02_model.R", inputs = "data/cohort.csv")  # run from the project root
em$value("model.n", 412L)
em$interval("model.or", 2.5, 1.8, 3.4, digits = 2)
em$value("model.p", 0.012, digits = 3, of = "model.or.point", family = "secondary")
em$correction("secondary", "holm")
alpha <- em$parameter("alpha", 0.05)
em$software("survival")
em$dataset("vigibase", "data/vb.csv", extracted = "2024-03-01",
           covers = c(NA, "2023-12-31"), fingerprint = "3f9a1c2b7e4d5a60")
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
- Data that are not the real data are declared so: `em.add_input("data/simulated.csv",
  synthetic=True)` (`synthetic = TRUE` in R). G1 then names each result the manuscript
  quotes from that run, and fails at submission. Only a worked example or a teaching paper
  sets `demonstration: true` in `paper.yaml`, which the title page then states; never set it
  to get a paper past the check.
- The data are named by what identifies them, with `em.dataset()`: the date they were
  extracted, the period they cover, the source's version where it has one, all ISO dates
  printed in the paper's English. `fingerprint` pins the date to the file; the first run
  without it is refused and prints the pin, and a new extract under the old pin is refused,
  so the date changes with the data. A date as a string value is held to its display: an
  ISO date may be printed "1 March 2024", "March 2024" or "2024", never another date.
- Units are not rendered. Write `{{results.case.pct_serious}}%` in the text.
- NumPy integers are refused; pass `int(x)`. Years and study periods are numbers like any
  other: emit them.
- An R string holding digits is not refused the way Python refuses it. Do not publish
  `"12.3 (95% CI 10.1 to 14.9)"` as one value; publish the three numbers.
- What the data can answer, counted before the analysis is settled, is published like any
  result, under `feasibility.` from a script of its own (`analysis/00_feasibility.py`); the
  [analysis-plan](../analysis-plan/SKILL.md) skill lists what to count.

### Arithmetic between results, and flows

G8 checks the arithmetic the analysis declares between results, with `em.relation()`, and
the counts of a flow diagram, with `em.flow()`, and only that. When a paper declares how its
results relate (a sum, a difference, a ratio, an upper bound or an order), draws a CONSORT or
PRISMA flow, or `check` warns under G8, read
[references/arithmetic-and-flows.md](references/arithmetic-and-flows.md).

### The data, held to the data dictionary

With a `design/data_dictionary.yaml`, hand each table read to `em.check_data(table)` (R:
`em$check_data(table)`); [references/data-quality.md](references/data-quality.md) has the
counts and their findings.

**Never edit `results/`.** The fragments are machine-written and digested. An edited one is
`results-edited`, the write guard refuses the edit where the hooks run, and
`manuscript-guard verify` re-runs the analysis in a scratch copy and compares value by value.
An output written without the emitter: [references/harvest.md](references/harvest.md).

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
  `{{figure.key}}` inserts `figures/<key>.<ext>`. The build prints the table's number
  before its emitted caption ("Table 2. Reports by drug group."), so emit the caption
  without one. A figure's caption is the paragraph under it, opened with its ref:
  `{{ref.figure.forest}}. Forest plot of ...`. A mistyped figure key passes `check` and
  fails at `build`; a mistyped table key is named only at `build`, though `check` reports
  the intended table as `unplaced-table`.
- `{{method.key}}` prints nothing. It ends Methods text and points it at a step the
  analysis marked with `em.step("key")`; the [methods-writer](../methods-writer/SKILL.md)
  skill covers it.
- Point at a table or a figure by its key, and the build prints its number:
  `{{ref.table.baseline}}` prints "Table 1" if it is the first table the main text places
  (its files in print order, `main.md` first), and "Table S1" for the supplement's first, or
  the form the journal profile's `pointers:` gives ("eTable 1"). Move the table and every
  mention follows. For a list or a range, `{{num.table.key}}` prints the number alone:
  "Tables {{num.table.a}} and {{num.table.b}}". The words before a num have to name its kind
  and its document, or `pointer-word-mismatch`. A ref to a key nothing places is
  `unresolved-binding`. Where a document also places that kind by hand, sends some to the
  journal as files (`displays:` in paper.yaml), or places the key twice, the count is not
  known and the ref is `ref-number-unknown`: type that pointer.
- A pointer typed as text ("Table 2") is held to what each document places by binding:
  `pointer-to-nothing` past the last one, and in the main text `display-not-cited` and
  `cited-out-of-order` (ICMJE's order of first citation). Refs count as citations.
  `manuscript-guard bind --pointers` lists each typed pointer with the binding that prints it
  as it reads now, and `--apply` writes them.
- Text inside HTML comments is ignored and never reaches the document. A number inside a
  fenced code block is judged as code, and a number in a string literal there is a claim.
- A sign beside a binding is typed as itself (`≈`, `±`, `≤`) or as maths between dollar
  signs (`$\approx$`). Outside dollar signs a TeX command is left out of the document
  with the number after it: `\approx {{results.cohort.n_reports}}` prints neither.
  `check` asks pandoc how it reads the text and reports this as `tex-in-the-text`, at
  its line, failing from `drafting` on; `build` refuses it at every stage. Without pandoc
  on PATH `check` passes it and says in a note (`tex-not-judged`) that the build judges it.
- `manuscript/supplementary/` is checked the same way and built as its own document.

In a LaTeX manuscript, a binding is one command: `\mg{results.key}`, `\mg{lit.key}`,
`\mg{table.key}` inside the float you caption, `\mg[width=\linewidth]{figure.key}` with
`\includegraphics`'s options, and `\mg{method.step}`. Point at a table or a figure with
`\ref`. `manuscript-guard values` writes `mgvalues.sty` from the results, so that the `.tex`
compiles in any editor with the numbers in: run it after the analysis and commit it; `check`
fails a stale one. A number in a siunitx command, `\num{0.42}`, cannot be bound, since
siunitx parses a number and a value prints as text: type the unit beside the binding.

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
   relative to the project root. In a LaTeX manuscript it offers and writes `\mg{...}`. `bind --apply` alone takes every unambiguous
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
     - id: maf-threshold
       pattern: '(?i)minor allele frequency (?:below|<) 1%'
       why: Standard genotype quality-control threshold, stated in the Methods.
       added_on: 2026-09-24
   ```

   `id` is optional. The report and `explain` cite the rule by it, as
   `project:maf-threshold`, and without it by the start of the pattern.

   A name that contains digits, such as a gene or a product code, goes under `terms:`.
   A name typed with a subscript or a superscript is declared without the signs:
   `terms: [CO2]` covers `CO~2~` as well as `CO2`, and `HbA~1c~` needs nothing, since
   `HbA1c` is built in. An isotope is declared by its mass and its element, `terms: [18F]`
   for `^18^F-FDG`. An exponent on a unit, `kg/m^2^` or `s^-1^`, is read as `m²` is
   and needs nothing either; `10^6^` is a number. A tilde that nothing closes is no
   subscript: `pH~2` is a number after "about", and is bound or written out.

   If `p < 0.05` is reported although it is in the Methods, look above it for a line that
   starts with `#`, or sits over a line of `-` or `=`, inside a paragraph, a list item or a
   quotation. Pandoc prints that line as text, not as a heading, and the gate ends the
   Methods there. Do not add a convention. If the line is text ("# of reports" moved to the
   start of a line by a hard wrap), rewrap it or write `\#`. If it was meant as a heading,
   put a blank line before it. If the `-` line under it was meant as a rule, put the blank
   line before the rule.

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
| `value-splits-paragraph` | the value prints display maths, a LaTeX environment, an HTML block tag or a line break into its sentence, where it can break the paragraph in parts in Word. Write that part in the `.md`, as a block of its own, and bind only the numbers in it |
| `unquoted-result` | a published value is quoted nowhere: quote it, or emit with `quoted=False` |
| `typed-parameter`, `typed-software-version`, `typed-dictionary-release` | the analysis declares this threshold, version or dictionary release: bind `{{results.param.…}}`, `{{results.software.…}}` or `{{results.dictionary.…}}` rather than typing it |
| `parameter-unread` | the script declares a parameter and never reads the value `parameter()` returns: use it in the step it stands for, or remove it |
| `threshold-undeclared` | a warning: a threshold typed in the Methods that no declared parameter has. Declare it if the code applies it; if the code applies another value, the Methods are wrong |
| `unplaced-table` | an emitted table is never placed with `{{table.key}}` |
| `pointer-to-nothing`, `display-not-cited`, `cited-out-of-order` | a typed "Table 3" names no table the document places, a table is cited nowhere, or the first citations are not in the order the tables are numbered. Name it with `{{ref.table.key}}` (`bind --pointers` does it), or move the table |
| `pointer-word-mismatch` | the words around a `{{num.…}}` or `{{ref.…}}` name another kind or the other document ("Figure {{num.table.a}}"). Fix the words, or write the ref whole |
| `caption-names-another` | a caption beside a table or figure (typed under a figure, above or under a table, or emitted by the analysis with a number) names another one. Write the caption's number as `{{ref.figure.key}}`, or emit the caption without its number |
| `ref-number-unknown` | the build cannot number this ref: its kind is also placed by hand or sent as files in that document, or its key is placed twice. Type that pointer |
| `hand-authored-table` | emit the table |
| `script-newer`, `input-changed` | re-run the script that wrote the results; where the input is a dataset's, with the date of the new extraction and its pin |
| `dataset-pin-mismatch`, `dataset-read-differs`, `dataset-value-unrecorded` | the results were computed from other data than the extraction the dataset dates, or a dataset's value was typed into a fragment: re-run the scripts that read the old data, through the emitter |
| `data-date-not-declared` | a warning: a date of the data typed into the script as a string. Declare the data with `em.dataset()` and bind `{{results.dataset.<name>.extracted}}`; a date the study chose is `em.parameter()` |
| `dataset-date-english` | a warning: the dataset's date was printed in the English paper.yaml declared when the analysis ran; run it again |
| `input-missing` | restore the input, or stop declaring it, then re-run |
| `input-not-fetched` | a warning: the input is a Git LFS or git-annex pointer that cannot be compared with the results (an MD5 key, an LFS extension, or results written before the emitter recorded `raw_sha256`). Fetch it to check it, or re-run where it is fetched |
| `results-edited`, `no-digest` | re-run through the emitter; never edit the fragment |
| `duplicate-quantity` | a warning: two quoted keys hold the same value. One quantity? Publish it once. A coincidence? Nothing to do |
| `divergent-display` | the same value is displayed two ways; pick one display |
| `declared-same-but-differs` | two keys declared one quantity with `same_as=` have drifted apart |
| `interval-reversed` | the text quotes the upper bound first; swap the two bindings |
| `relation-broken`, `flow-broken` | the analysis's own numbers disagree with the arithmetic it declared: find the computation that is wrong, or the declaration that names the wrong keys |
| `relation-rounding` | a warning: the printed parts do not give the printed result. Print one more digit, or say each is rounded on its own |
| `relation-unresolved` | a declared relation names a key nothing emits, or one that is not a number |
| `estimate-outside-interval`, `interval-inverted` | fix the interval in the analysis, with `interval()` |
| `quoted-alone` | a warning: a p value quoted in a sentence without its estimate, or a share without either of its counts. Quote them together: n/N (%) |
| `interval-not-quoted-whole` | a warning: the estimate is quoted, and no sentence anywhere quotes both bounds of its interval |
| `interval-level-differs`, `spread-label-differs` | a warning: the level written beside an interval ("90% CI"), or the label beside a dispersion ("SE"), is not the one the analysis emitted. Write the one emitted, or bind what the text means |
| `interval-level-undeclared` | a warning: an interval is quoted and its level was not emitted. Say it once: `Emitter(__file__, ci_level="95%")`, `mg_emitter(..., ci_level = "95%")` |
| `family-uncorrected` | a warning: a family of more than one p value, and no `correction()` declared for it. "none" with a reason is a declaration |

## If you are a model doing this

Never type a number the analysis produced, even one you can read straight off the results
file. Bind it. The check would catch the literal, and binding is the whole point.

Never run `bind --apply` without `--only` on a manuscript you did not just write. Read each
suggestion, and apply the ones whose meaning, not just value, is right.
