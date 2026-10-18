# What the plan answers for each design

Beyond the seven sections every plan has, a plan for a named design (`study_type` in
`paper.yaml`) answers the questions below, one section each. G12 asks for a heading that
names the section and something under it; whether the answers are sound is the author's and
the panel's to judge. Each question cites the guideline item it comes from, read on its own
page on 2026-10-15. Write the answer before the analysis exists, so that a change to it is a
deviation.

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
