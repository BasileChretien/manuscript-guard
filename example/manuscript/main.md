---
title: "Reporting of hepatic injury with example-drug: a disproportionality analysis of a synthetic spontaneous reporting database"
---

# Abstract

**Background.** Drug-induced hepatic injury is a common reason for regulatory action.
**Methods.** Disproportionality analysis of a synthetic spontaneous reporting database
covering {{results.cohort.period_start}} to {{results.cohort.period_end}}, comparing
reports of hepatic injury for example-drug against all other drugs.
**Results.** Of {{results.cohort.n_reports}} reports, {{results.case.n_cases}} described
hepatic injury with example-drug. The reporting odds ratio was {{results.ror.point}}
(95% CI {{results.ror.ci_low}} to {{results.ror.ci_high}}).
**Conclusions.** Reporting of hepatic injury is disproportionate for example-drug in these
synthetic data. Disproportionality is not incidence and cannot establish risk.

# Introduction

Drug-induced hepatic injury remains among the commonest reasons for regulatory action on a
marketed medicine. In a national cohort, the crude incidence was
{{lit.background.reported_incidence}} per 100 000 person-years
[@fictionalHepaticCohort2021], and a disproportionality signal has been reported for the
drug class as a whole (ROR {{lit.background.class_ror}}) [@fictionalClassSignal2019]. The
national agency estimated that {{lit.agency.withdrawn_estimate}} patients had been exposed
by the end of its last published review.

Whether the signal extends to example-drug specifically has not been examined.

# Methods

We analysed a synthetic spontaneous reporting database covering
{{results.cohort.period_start}} to {{results.cohort.period_end}}, a period of
{{results.cohort.n_years}} years. Reports were included without restriction on age or sex.
Each record carries a unique report identifier and the generator emits no duplicates, so no
de-duplication step was applied; a real database would require one, and its absence here is
a property of the synthetic data rather than a design choice.

Hepatic injury is the single event term used by the data generator. Real work would need a
case definition — a MedDRA Standardised Query or an explicit preferred-term list — and the
choice of definition would change the counts. The terms actually used are published in
Table S1, emitted from the lists the analysis filtered on rather than retyped, which is what
RECORD 6.1 asks for and what makes a case definition checkable.

The reporting odds ratio was computed from a 2 x 2 table contrasting reports of hepatic
injury with all other reported events, for example-drug against all other drugs in the
database. Confidence intervals were derived from the standard error of the log odds ratio
and are reported as 95% confidence intervals throughout, two-sided at an alpha of 0.05.
A signal was defined by the classical criterion: at least 3 cases together with a lower
bound of the confidence interval of the reporting odds ratio above 1. No p-value threshold
was used as a decision rule, which is not how a disproportionality analysis reaches its
conclusion.

Reporting follows the checklist declared in `paper.yaml`.

<!--
That checklist is a demonstration profile, not a published guideline, which is why no
guideline is named in the prose above. A real study of spontaneous reports would name
READUS-PV — the guideline for disproportionality analyses, for which this repository ships
a transcription recipe — declare it in `reporting_guideline:`, and complete its checklist.
G5 reconciles the two: name a guideline in the text without declaring it and the run says
so. An adherence claim nothing checks is exactly the untraceable assertion this toolkit
exists to remove, and it is a claim about the paper's own conduct.

An earlier version of this file said "Analyses followed STROBE and RECORD-PE" while
declaring neither — and RECORD-PE, which is for routinely collected health data, is the
wrong guideline for a spontaneous-report study altogether. Nothing caught it, because
nothing read the sentence. This comment and that gate are the same fix.
-->

# Results

The database contained {{results.cohort.n_reports}} reports, of which
{{results.cohort.n_drug_reports}} named example-drug. Hepatic injury was reported in
{{results.case.n_cases}} of these; {{results.case.n_serious}} were flagged as serious
({{results.case.pct_serious}}%). Baseline characteristics are shown in Table 2.

{{table.baseline}}

Reporting of hepatic injury was disproportionate for example-drug, with a reporting odds
ratio of {{results.ror.point}} (95% CI {{results.ror.ci_low}} to
{{results.ror.ci_high}}; 90% CI {{results.ror.ci90_low}} to {{results.ror.ci90_high}}). The
estimate is shown in Figure 1, and the counts it was computed from in Table 3, so a reader
can reconstruct it.

{{table.two_by_two}}

{{figure.forest}}

# Discussion

The reporting odds ratio observed here exceeds the class-level estimate of
{{lit.background.class_ror}} reported previously [@fictionalClassSignal2019], although the
two are not directly comparable: that analysis pooled the class and drew on a different
reporting period.

Disproportionality is not incidence, and nothing in these data supports a rate. The cohort
incidence of {{lit.background.reported_incidence}} per 100 000 person-years
[@fictionalHepaticCohort2021] is the only population-level figure available, and it
predates the marketing of example-drug.

Several limitations follow from the design. Spontaneous reports are subject to notoriety
bias, and the denominator is unknown. Grade 3 and higher events cannot be distinguished
from milder ones in these data. The exposure figure of
{{lit.agency.withdrawn_estimate}} patients rests on a printed agency report that is no
longer publicly available, and is recorded as an author attestation rather than a stored
source.

# Data availability

The synthetic dataset, the code that generates it and the analysis that reads it are all in
this repository. No real patient data were used, and no ethical approval was required.

# Funding

This work received no funding.

# Competing interests

None declared.
