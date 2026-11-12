# Analysis plan

Agreed 2026-08-03, before the analysis was written.

This is the worked example's plan, and it is short because the study is small. A real plan
is longer, but not differently shaped: what is being asked, how it will be answered, and
what would count as an answer — written down before the answer is known.

## Research question

Is hepatic injury reported disproportionately often for example-drug, relative to all other
drugs in the same database?

The question is about *reporting*, not about risk. Nothing in this design can establish
incidence, and the manuscript must not read as though it could.

## Design

Case/non-case (disproportionality) analysis of a spontaneous reporting database. This is
the standard design for signal detection when there is no denominator, and its limits are
the reason the question is phrased as it is.

## Population and data source

All reports in the synthetic database for the period it covers, without restriction on age
or sex. Age group (`age_group`) and sex (`sex`), the two patient characteristics the
database records, are described among the reports with the drug and the others; the ratio
adjusted for both was added later (Deviations, item 5). Records carry unique identifiers;
de-duplication is therefore not required for these data, and its absence is a property of
the generator rather than a decision.

## Exposure

Reports naming example-drug (`exposed`, from `drug`), against all reports naming any other
drug. No stratification by dose, indication or concomitant medication: the generator emits
none of those.

## Outcome

Reports of hepatic injury (`hepatic`, from `event`), the single event term the generator
emits. Real data would need an explicit case definition, and the choice would change the
counts.

## Analysis

Reporting odds ratio from the 2 x 2 table of drug against event, with a Wald interval on the
log scale. One comparison is planned, so no multiplicity adjustment. A two-sided threshold of
p < 0.05 is stated for convention; the interval, not the threshold, carries the conclusion.

Seriousness (`serious`) is reported as a proportion of the cases, descriptively.

## Known answers

Three controls, each put through the same 2 x 2 table and Wald interval as the ratio, by the
same script. They were added after the first results (Deviations, item 8).

- A simulated control: reports drawn as the database's are, with hepatic injury planted for
  example-drug at twice the odds of the other drugs. Its interval should hold the ratio
  planted and leave out one, the null.
- A positive control: the third comparator and hepatic injury. The generator gives that drug
  the least hepatic injury of the four, and the others more, example-drug most, so its rates
  give a ratio of about 0.52. Its interval should hold that ratio and leave out the null.
- A negative control: the first comparator and nausea, for which the generator's rates give
  a ratio close to one. Its interval should hold the null.

```yaml
controls:
  - key: control.simulated
    kind: simulated
    of: ror.*
    expected: 2
    rule: holds-expected
    null: 1
  - key: control.positive
    kind: positive
    of: ror.*
    expected: 0.52
    rule: holds-expected
    null: 1
  - key: control.negative
    kind: negative
    of: ror.*
    expected: 1
    rule: holds-null
```

## Planned results

The results the paper will report, each by the key the analysis emits it under:

- `case.n_cases`: the cases, reports of hepatic injury with the drug
- `ror.*`: the reporting odds ratio and its 95% interval
- `case.pct_serious`: the proportion of the cases that were serious

## Software

Python, with the packages below. The database is synthetic, so no package is written for
it; for a real source, the packages written for it would be looked for first and named
here, each with the steps it does.

- `Python` 3.10 or later: the run records the version it ran under.
- `pandas`: `DataFrame()` holds the reports for the adjusted model.
- `statsmodels`: `glm()` with a binomial family fits the adjusted model. The crude ratio
  and its Wald interval are computed from the 2 x 2 table with the standard library.
- `matplotlib`: `subplots()` draws the forest plot.

## Sample size

Fixed by the database. No power calculation: the analysis is descriptive of what was
reported, and there is no hypothesis test the study was designed to detect.

## Sensitivity analyses

None planned. With one exposure, one outcome and no covariates there is nothing to vary
that would not be a different study.

## Deviations from the plan

Eight. The first two came after the first review round, both additive rather than a change
of approach:

1. The 2 x 2 counts were added to the Results as a table. The plan implied them; the first
   draft reported only the ratio, which left the estimate unreconstructable.
2. The Methods gained explicit paragraphs on de-duplication and the case definition. Both
   were assumptions in this plan rather than statements in the paper.

No analysis was added, removed or re-run as a result of those two. Recorded here because a
deviation nobody wrote down is indistinguishable from having tried several things.

3. After the second review round (2026-08-04), the Methods replaced the p < 0.05 threshold
   with a signal criterion: at least three cases and a lower bound of the 95% interval
   above 1. The plan let the interval carry the conclusion and set no minimum number of
   cases. The criterion was written after the crude result was known, and no reviewer asked
   for it; the analysis has applied it since the third round (2026-10-09).
4. The next day (2026-08-05), the main estimate was also given with its 90% interval, for
   comparison with signal-detection practice. It is a second interval on the planned
   estimate, added after that estimate was known; the conclusion and the signal criterion
   rest on the 95% one. The Methods have said so since the third round (2026-10-09), and
   until then described every interval as 95%.
5. In the fourth review round (2026-10-09), a reporting odds ratio adjusted for age group
   (`age_group`) and sex (`sex`) by logistic regression was added beside the planned crude
   ratio. It is an analysis added after the crude result was known; the Methods describe it
   and Table S2 prints its model as it was fitted.
6. The variables are named in backticks, as a data dictionary names them, so that G12 can
   hold a dictionary to this plan (2026-10-21): a change of wording, not of the analysis.
7. The Software section was added (2026-11-09), naming the packages the analysis had
   loaded from the start, so that G12 can hold the plan to the scripts: a record, not a
   change of the analysis.
8. Three controls were added on 2026-11-09, after the first results were known:
   control.simulated, control.positive and control.negative (Known answers). The negative
   control was chosen by the generator's order, the first event it lists after hepatic
   injury and its first comparator, and its rule written before it was run. The positive
   control was first example-drug and nausea, within 0.25 of 0.82; review round 12 found
   that its interval held the null, so it would have passed an analysis that finds nothing,
   and it was replaced the same day by the third comparator and hepatic injury, the pair
   whose ratio the generator's rates put furthest from one, the study's own pair aside. Its
   estimate had been seen by then. None of the planned results moved.
9. The Methods name statsmodels and not pandas or matplotlib, and cite none of the three
   (2026-11-12): `pandas`, `statsmodels`, `matplotlib`. The example's references are
   invented, and none describes a package, so a citation of one here would be false. A
   real paper names in its Methods each package the analysis uses, and cites there the
   reference its authors ask for. A record, not a change of the analysis.
