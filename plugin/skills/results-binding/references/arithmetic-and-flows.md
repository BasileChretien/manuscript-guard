# Arithmetic between results, and flows

Part of the results-binding skill, read when a paper adds, subtracts or divides its results,
or draws a CONSORT or PRISMA flow.

G8 checks the arithmetic the analysis declares between results, and only that. It does not
search the text for numbers that might add up:

```python
em.relation("sum", "cohort.n_reports", ["table2x2.a", "table2x2.b", "table2x2.c", "table2x2.d"])
em.relation("difference", "risk.difference", ["risk.treated", "risk.control"])
em.relation("ratio", "rate.per_1000", ["events.n", "person_years"], scale=1000)
em.relation("at_most", "patients.with_event", ["patients.n"])
em.relation("in_order", "cohort.period_start", ["cohort.period_end"])   # dates or numbers

em.flow("consort",
        stages={"Assessed for eligibility": 412, "Randomised": 300},
        exclusions=[{"Not meeting criteria": 87, "Declined": 25}],
        arms={"Drug": 151, "Placebo": 149})
```

In R, `em$relation("sum", "cohort.n", c("cohort.n_men", "cohort.n_women"))`. A flow's stages,
reasons and arms are named vectors there: `stages = c("Randomised" = 300, ...)`.

- **Keys may be another script's.** G8 reads every fragment together.
- **Values are compared exactly, displays within their rounding.** A sum of counts must be
  exact. A float relation holds to its last bits, so emit values unrounded.
- **Printed numbers get a warning when the arithmetic does not hold for them.** For example,
  2.4 less 1.1 is 1.3, and the difference is printed 1.2. That is a warning: print one more
  digit, or say in the text that each number is rounded on its own.
- **A flow writes each count as a key.** The keys are `flow.<key>.stage.<n>`,
  `flow.<key>.excluded.<n>.<m>` and `flow.<key>.arm.<n>`. Bind them in the text, and have the
  diagram's script read them from the results.
- **The emitter refuses a flow whose arithmetic fails.** Each stage less its exclusions must
  be the next stage, and the arms must sum to the last stage.
- **Overlapping reasons.** Where one record can be excluded for several reasons at a step,
  name that step: `overlapping=[3]` for the step from stage 3 to stage 4 (`overlapping = 3`
  in R), or `True` for every step. Its reasons may then sum to more than the step removed,
  and the stages still have to agree. Every other step's reasons must still sum exactly.
- **PRISMA 2020.** The records removed before screening (duplicates, automation, other) are
  the exclusions of the first step. Where a report is excluded for several reasons, name the
  step from reports assessed to reports included in `overlapping`. Studies are not a
  subtraction from reports: end the flow at the reports, and declare the studies `at_most`
  the reports included.
- **A 2x2 table.** Declare each margin as a sum of its cells, and the total as the sum of all
  four.
