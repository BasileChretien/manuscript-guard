# What the plan answers for each design

Beyond the seven sections every plan has, a plan for a named design (`study_type` in
`paper.yaml`) answers the questions below, one section each. G12 asks for a heading that
names the section and something under it; whether the answers are sound is the author's and
the panel's to judge. Each question cites the guideline item it comes from, read on its
own page on the date its entry in `study_types.yaml` gives. Write the answer before the analysis exists, so that a change to it is a
deviation. A study that is none of the designs below has `study_type: other`, and its plan
the seven sections only.

G12 finds a section by the words of its heading. Where the plan answers it under a heading of
the author's own words and G12 says the plan says nothing about it, name the section on that
heading with the identifier the warning gives, the section's name with a hyphen for each
space: `## Study sample {#sampling}`, `## Power {#sample-size}`. Keep the author's words, and
do not rename a heading to fit the check. The Deviations cannot be named so: every other
check reads it by its words, so keep a heading such as "Deviations from the plan".

## trial

The paper follows CONSORT, the protocol SPIRIT 2025.

- **Estimand.** What is the treatment, the population, the variable, the handling of each
  intercurrent event (treatment policy, hypothetical, composite, while on treatment,
  principal stratum), and the population-level summary? (ICH E9(R1), A.3.2 and A.3.3)
- **Sample size.** How was the number decided, and on which assumptions? (SPIRIT 2025, 19)
- **Randomisation.** How is the sequence generated and concealed, who is blinded, and when
  may the blind be broken? (SPIRIT 2025, 21a to 24c)
- **Missing data.** How will missing data be handled? (SPIRIT 2025, 27c)
- **Sensitivity analyses.** Which, and which assumption of the main analysis does each
  test? (SPIRIT 2025, 27d; ICH E9(R1), A.5.2.1)
- **Interim analyses.** Is there one, with what stopping rule, and who sees it and
  decides? (SPIRIT 2025, 28a and 28b)

## cohort

The paper follows STROBE, or an extension of it (RECORD for routinely collected data);
a cohort that emulates a target trial follows TARGET.

- **Time zero and follow-up.** When does follow-up start, what is the at-risk window, and
  how is loss to follow-up handled? Emulating a trial, follow-up starts at assignment.
  (STROBE, 6a and 12d; TARGET, 7d)
- **Confounding.** Which confounders and effect modifiers, which adjustment set, and why
  each variable is in it? (STROBE, 7 and 12a)
- **Missing data.** (STROBE, 12c)
- **Sensitivity analyses.** Which subgroups, interactions and sensitivity analyses?
  (STROBE, 12b and 12e)

## case-control

The paper follows STROBE, or RECORD.

- **Cases.** What is the case definition, and where and how are cases found? (STROBE, 6a)
- **Controls.** Where and how are controls selected, and why these? (STROBE, 6a)
- **Matching.** On what, how many controls per case, and how does the analysis account for
  it; or that there is none? (STROBE, 6b and 12d)
- **Confounding.** (STROBE, 7 and 12a)
- **Missing data.** (STROBE, 12c)

## cross-sectional

The paper follows STROBE, or RECORD for routinely collected data. Exposure and outcome are
measured at one time, so the plan says which question that can answer and which it cannot:
a prevalence, an association, not which came first.

- **Sampling.** How are participants sampled and recruited, and does the analysis allow
  for it (weights, clusters, strata)? (STROBE, 6a and 12d)
- **Measurement.** How is each variable measured, with which instrument, and the same way
  in every group? (STROBE, 8)
- **Bias.** Which sources of bias, non-response among them, and what is done about each?
  (STROBE, 9)
- **Sample size.** How was the study size arrived at? (STROBE, 10)
- **Confounding.** Which confounders and effect modifiers, which adjustment set, and why
  each variable is in it? (STROBE, 7 and 12a)
- **Missing data.** (STROBE, 12c)
- **Sensitivity analyses.** Which subgroups, interactions and sensitivity analyses?
  (STROBE, 12b and 12e)

## diagnostic-accuracy

The paper follows STARD 2015. The index test is the plan's exposure and the target
condition its outcome: G12 reads a heading that is "Index test" or "Target condition"
alone as such: plural, with "(s)" or a qualifier in brackets, and numbered "3.", "3.1",
"3)", "A." or "III.". Any other heading, "10a. Index test" or "Index test: CT
angiography", names the section exactly: `## 10a. Index test {#exposure}`.

- **Sampling.** Where and how are potentially eligible participants identified, and are
  they a consecutive, random or convenience series? (STARD 2015, 7 to 9)
- **Reference standard.** Which, in enough detail to repeat it, and why that one?
  (STARD 2015, 10b and 11)
- **Thresholds.** The positivity cut-offs or result categories of both tests, and which
  were set in advance. (STARD 2015, 12a and 12b)
- **Blinding.** Do those who read each test know the other's result or the clinical
  information? (STARD 2015, 13a and 13b)
- **Indeterminate results.** How are results that cannot be read handled? (STARD 2015, 15)
- **Missing data.** Missing results of either test. (STARD 2015, 16)
- **Sample size.** How many, with how many having the condition, and how it was worked
  out. (STARD 2015, 18)

## case-report

The paper follows CARE (2013). A case report describes one patient's care after it was
given, so its plan is not asked for an analysis or for deviations (`not_asked` in
`study_types.yaml`): what it settles before the writing is what the report will say of
the patient, and what it must not. The patient is the population, read under a heading
that is "Patient information", "The patient" or "Patient" whole; the treatment is the
exposure ("Therapeutic intervention"), and the follow-up and its outcomes the outcome.
Under any other heading, "Case presentation" or "Patient history", name the population
exactly: `## Case presentation {#population}`.

- **De-identification.** Which details of the patient the report gives, and which it
  leaves out or blurs so that no one can recognise them. (CARE, 5)
- **Timeline.** The important dates and events of the case, in order, as a table or a
  figure. (CARE, 7)
- **Diagnostic assessment.** How the diagnosis was reached: the tests, the difficulties,
  the other diagnoses considered and, where it applies, the prognosis. (CARE, 8)
- **Patient perspective.** Whether the patient gives their own account of what they went
  through and of their care. (CARE, 12)
- **Informed consent.** That the patient, or whoever may decide for them, agreed to the
  publication, and how that is recorded. (CARE, 13)

## case-series

A descriptive case series, several patients who share a condition, an exposure or a
treatment described together with no comparison group of their own. It is not the
self-controlled case series, which is `self-controlled`. No general guideline is written
for case series: the paper follows PROCESS (2023), written for surgical case series, or
Kempen (2011), for uncontrolled case series in any field, and G5 accepts either. The plan
is asked for all seven sections, the analysis being the counts and summaries the series
will give. The sections cite PROCESS 2023. The comparison is found under a comparator,
a comparison group, a comparison with the literature, with controls, or with published,
other or previous studies or (case) series, historical or external controls or groups,
historical data, a benchmark, or a heading that is "Comparison" whole;
a comparison the analysis makes ("Multiple comparisons") or one within the series
("Comparison with baseline values") is not it: name such a heading exactly,
`## Comparisons {#comparison}`, where it is.

- **Case selection.** How the cases are found and chosen: from which records or referrals,
  over which period, and whether the series holds every case seen or only some. (PROCESS
  2023, 6c to 6f)
- **Follow-up.** How long and how often each patient is followed, by what means, and how
  those lost to follow-up are counted and explained. (PROCESS 2023, 6l and 7c)
- **Comparison.** What the results are set against, published studies, the current
  standard of care or a historical group, and why it is comparable. (PROCESS 2023, 8b)
- **Consent and ethics.** Whether an ethics committee approves the study or waives its
  approval, and how the patients' consent is obtained, or why it is not. (PROCESS 2023, 6b
  and 11)

## self-controlled

No reporting guideline is written for self-controlled designs; the paper follows STROBE.
The questions come from the methods literature: Petersen, Douglas and Whitaker, BMJ
2016;354:i4515, and Cadarette et al., Pharmacoepidemiol Drug Saf 2021, doi 10.1002/pds.5227.

- **Observation period.** Over what period are each case's events and exposures known, from
  when to when? (Petersen et al.)
- **Risk windows.** Which risk windows, how long, and what is control time; for a
  case-crossover, the focal and referent windows? (Petersen et al.; Cadarette et al.,
  Table 1)
- **Washout.** Which induction, lag and washout windows, and is there a pre-exposure period?
  (Cadarette et al., section 4; Petersen et al., Table 1)
- **Time-varying adjustment.** How is the observation period cut by age, season or calendar
  time? (Petersen et al.)
- **Assumptions.** How are event-dependent exposure, an event that ends observation, and
  recurrent events handled? (Petersen et al., Table 1)

## disproportionality

The paper follows READUS-PV (Drug Saf 2024;47:575-584).

- **Deduplication.** How are duplicate reports found and removed, and what else was done to
  the data before the analysis? (READUS-PV, 5b)
- **Case definition.** Which events and drugs, as coded, how are they grouped, and which
  roles of a drug count? (READUS-PV, 6a and 6c)
- **Comparator.** Against which reports are these compared, and why that reference group?
  (READUS-PV, 3, with 7a, 7b and 8b)
- **Measure.** Which measure of disproportionality, and which threshold, and why?
  (READUS-PV, 7b)
- **Sensitivity analyses.** Which restrictions, subgroups, stratifications or adjustments,
  and any case-by-case review? (READUS-PV, 7c and 7d)

## systematic-review

The paper follows PRISMA 2020, the protocol PRISMA-P 2015.

- **Eligibility.** Population, intervention, comparator, outcome, design, setting, time
  frame, language and publication status. (PRISMA-P, 8)
- **Search.** Which databases, registers and other sources, with dates, and a draft search
  for one database. (PRISMA-P, 9 and 10)
- **Selection and extraction.** How records are screened and selected, by how many people,
  and which data are extracted. (PRISMA-P, 11a to 13)
- **Risk of bias.** With which tool, at which level. (PRISMA-P, 14)
- **Synthesis.** When results are combined and how, how heterogeneity is assessed, and the
  summary where they are not combined. (PRISMA-P, 15a to 15d)
- **Certainty.** How meta-bias is assessed, and the confidence in the body of evidence.
  (PRISMA-P, 16 and 17)

## prediction-model

The paper follows TRIPOD+AI (BMJ 2024;385:e078378).

- **Predictors.** How are they chosen, defined and measured, and when? (TRIPOD+AI, 9a, 9b)
- **Sample size.** How was the size of each dataset arrived at? (TRIPOD+AI, 10)
- **Missing data.** (TRIPOD+AI, 11)
- **Model development.** How are the data split, the predictors handled, the model chosen
  and tuned, and how is it validated internally? (TRIPOD+AI, 12a to 12d and 13)
- **Performance.** Which measures of discrimination and calibration, and how would the
  model be updated? (TRIPOD+AI, 12e to 12g)
- **Fairness.** How is the model's performance across groups assessed, and why that way?
  (TRIPOD+AI, 14)
