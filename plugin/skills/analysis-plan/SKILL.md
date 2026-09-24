---
name: analysis-plan
description: Write the analysis plan in design/plan.md before the analysis exists, and record every deviation from it as it happens. Use at the start of a paper project, when check reports no-analysis-plan, plan-section-missing or plan-section-empty, or when the analysis is about to do something the plan did not say.
---

# Writing down what you meant to do, before you do it

A result is more credible when the analysis that produced it was written down first. This
is not because departing from a plan is wrong. A departure that was declared is a decision
a reader can weigh; one that nobody recorded looks exactly like having tried several
analyses and reported the one that worked.

G12 warns and never blocks, at any stage, including submission. That is deliberate:
exploratory work is real work, and a gate that stopped you writing code until a plan was
agreed would be bypassed the first afternoon it cost something. It also means the gate's
approval is worth very little. All the value is in what gets written.

## Where it lives

`design/plan.md`, in UTF-8. The path is fixed. A file saved in another encoding makes the
gate crash, and a crashed gate fails the whole check. `manuscript-guard init` scaffolds
the headings.

The gate matches any heading at any level, ignoring case, against seven requirements:

| Requirement | Headings that count | Headings that do not |
|---|---|---|
| question | Research question, Objective(s) | Aims, Hypothesis |
| design | Design, Study design | |
| population | Population, Study population, Participants, Data source | Data sources |
| exposure | Exposure(s), Intervention(s), Predictor | Predictors |
| outcome | Outcome(s), Endpoint | Endpoints |
| analysis | Analysis, Statistical analyses | Analyses, Methods |
| deviations | Deviations from the plan, Changes to the plan, Protocol amendments | |

The right-hand column is there because those headings look as though they should count and
are reported missing. Rename the heading; do not argue with the pattern.

Two things the gate gets wrong, so check them yourself:

- **Put a sentence directly under every heading.** A section is counted as empty when all
  its content sits in subsections, so a `## Population` holding only `### Inclusion` and
  `### Exclusion` is flagged.
- **An empty `## Analysis` is never flagged**, because the scaffold's own title,
  `# Analysis plan`, already satisfies the requirement. The gate will not tell you the most
  important section is blank.

`TBD`, `TODO`, `n/a`, dashes and "see below" count as empty. `Sample size` and
`Sensitivity analyses` are scaffolded but not checked; fill them anyway.

## Writing it

The test of a plan is whether a deviation from it would be recognisable. "Appropriate
statistical methods will be used" cannot be deviated from, so it records nothing. For each
section, write what a reader would need in order to say afterwards "that is not what they
said they would do":

- Research question: one question, stated as the quantity you will estimate.
- Design: the design, and why it answers this question rather than a neighbouring one.
- Population and data source: who or what is included and excluded, over what period,
  from which version of which source.
- Exposure: the definition as it will be coded, and the comparator.
- Outcome: the definition as it will be coded. Where two reasonable definitions would
  give different counts, choose here, before you have seen which one gives the answer.
- Analysis: the estimator, the model, the covariates, what happens to missing data, any
  threshold, and how many comparisons are being made.
- Sample size: what you expect to have and what it can detect, or why that cannot be
  calculated in advance.
- Sensitivity analyses: which ones, and which result would change your conclusion.

Numbers in the plan are not checked. G2 reads only `manuscript/`, and the plan does not go
in the submission pack.

## Dating it

The gate cannot tell when the plan was written, and nothing in the toolkit can. Only a
record outside the project can: a commit of `design/plan.md` made before the first
analysis script, or a registration with whatever registry the field uses. Tell the author
which is available to them. Registering is their decision and their account, not yours.

Fill in the `Agreed <date>` line with the real date.

## Recording a deviation

When the analysis departs from the plan, write it under the deviations heading at the time,
not at the end. For each one:

- when it happened, and what prompted it;
- what the plan said, and what was done instead;
- why;
- whether anything was re-run because of it, and whether the result moved.

`None so far.` is a legitimate entry as long as it is true. Every deviation also belongs
in the paper's Methods; the [methods-writer](../methods-writer/SKILL.md) skill covers that.

## If you are a model doing this

Do not write the plan from the analysis code. A plan reconstructed after the fact is exactly
what the plan exists to rule out, and the gate cannot tell the difference, so it will
approve it. If the analysis has already started, say so in the plan: "Written on <date>,
after the following had been run: …". That sentence is worth more than a plan that
pretends otherwise.

Do not fill sections with generic text to clear the warnings. A vague section passes the gate
and misleads the reader. An empty one at least shows what is still undecided. If a section
cannot be written yet, ask the author the question it needs answered.
