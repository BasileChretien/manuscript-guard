# Supplementary methods

## Table S1. Code lists used to identify the outcome

Everything under `manuscript/supplementary/` is read by the same gates as the paper — a
number here is a binding or a defect, exactly as in `main.md` — and built as its own
document, so it does not count against the journal's word limit and can be uploaded to the
supplementary slot rather than pasted onto the end of the manuscript.

The case definition belongs here rather than in the Methods because it is a list, and because
a reader checking it wants the whole list rather than a sentence about it. It is emitted from
the terms the analysis filtered on, so the definition in this table and the definition the
code applied cannot come apart.

{{table.outcome_codes}}

## Sensitivity of the estimate to the interval quoted

The primary analysis reports a 95% confidence interval of {{results.ror.ci_low}} to
{{results.ror.ci_high}}. The narrower 90% confidence interval, {{results.ror.ci90_low}} to
{{results.ror.ci90_high}}, is given for readers comparing this estimate with signal-detection
thresholds that use it. Both exclude the null, so the conclusion does not turn on which is
quoted.

<!--
Each interval is one `interval()` call and carries its level, so quoting either one upper
bound first is refused, and the two are never compared with each other — a narrower interval
nested inside a wider one is correct rather than a contradiction.

An HTML comment, because this paragraph is about the toolkit rather than about the study, and
because its own percentages would otherwise be reported findings. It reaches no document.
-->

## Reporting

This supplement is referred to from the Methods and is listed in the submission manifest as
its own file, alongside the manuscript rather than inside it.
