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
or sex. Records carry unique identifiers; de-duplication is therefore not required for these
data, and its absence is a property of the generator rather than a decision.

## Exposure

Reports naming example-drug, against all reports naming any other drug. No stratification by
dose, indication or concomitant medication: the generator emits none of those.

## Outcome

Reports of hepatic injury, the single event term the generator emits. Real data would need
an explicit case definition, and the choice would change the counts.

## Analysis

Reporting odds ratio from the 2 x 2 table of drug against event, with a Wald interval on the
log scale. One comparison is planned, so no multiplicity adjustment. A two-sided threshold of
p < 0.05 is stated for convention; the interval, not the threshold, carries the conclusion.

Seriousness is reported as a proportion of the cases, descriptively.

## Sample size

Fixed by the database. No power calculation: the analysis is descriptive of what was
reported, and there is no hypothesis test the study was designed to detect.

## Sensitivity analyses

None planned. With one exposure, one outcome and no covariates there is nothing to vary
that would not be a different study.

## Deviations from the plan

Two, both after the first review round and both additive rather than a change of approach:

1. The 2 x 2 counts were added to the Results as a table. The plan implied them; the first
   draft reported only the ratio, which left the estimate unreconstructable.
2. The Methods gained explicit paragraphs on de-duplication and the case definition. Both
   were assumptions in this plan rather than statements in the paper.

No analysis was added, removed or re-run as a result. Recorded here because a deviation
nobody wrote down is indistinguishable from having tried several things.
