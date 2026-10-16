---
name: analysis-plan
description: Write the analysis plan in design/plan.md before the analysis exists, and record every deviation from it as it happens. Use at the start of a paper project, when check reports no-analysis-plan, plan-section-missing, plan-section-empty, feasibility-not-run, planned-result-missing, planned-result-unquoted, planned-results-unkeyed or plan-changed-after-results, or when the analysis is about to do something the plan did not say.
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
  calculated in advance. A limit on the data or the money available is a justification
  when it is said, with the smallest effect that number can detect (Lakens, *Collabra:
  Psychology* 8:33267, 2022, sets out the ways a sample size is justified).
- Sensitivity analyses: which ones, and which result would change your conclusion.

Numbers in the plan are not checked. G2 reads only `manuscript/`, and the plan does not go
in the submission pack.

## What the data can answer

Before the analysis section is settled, count what the data hold, with a script of the
project's own and not by reading the data yourself: `analysis/00_feasibility.py` or `.R`,
emitting through the emitter under `feasibility.`:

- the size of the cohort after each selection step;
- the outcome's events, or its prevalence;
- the missing values of each variable the analysis plans to use;
- the date range the data cover;
- the duplicates found, and how they were found;
- whatever else the design needs counted before it is fixed.

Write these into the plan as bindings, "about {{results.feasibility.n_reports}} reports":
nothing renders the plan, but the binding names the result, and G1 holds that result to the
script and the data that made it. A count too small to publish is small in the plan too.
At the `design` stage, G12 warns (`feasibility-not-run`) where the plan sets out an analysis
and nothing is emitted under `feasibility.`.

## What the paper will report

Add a section headed "Planned results" that lists, one item each, the results the paper will
report, each item opening with the key the analysis will emit it under, in backticks:

```markdown
## Planned results

- `case.n_cases`: the cases
- `ror.*`: the reporting odds ratio and its 95% interval
```

`ror.*` is every key under `ror.`. Agree the keys with whoever writes the analysis, since
they are its names. Once the analysis is under way, G12 warns where a listed key was never
emitted (`planned-result-missing`) or was emitted with `quoted=False`
(`planned-result-unquoted`). If a planned result will not be reported, say so under
Deviations, naming its key; that stands the warning down and is the record a reader needs.

## Dating it

The gate cannot tell when the plan was written, and nothing in the toolkit can. Only a
record outside the project can: a commit of `design/plan.md` made before the first
analysis script, or a registration with whatever registry the field uses. Tell the author
which is available to them. Registering is their decision and their account, not yours.

Fill in the `Agreed <date>` line with the real date.

## Recording a deviation

When the analysis departs from the plan, write it under the deviations heading at the time,
not at the end. For each one:

- the date, and what prompted it;
- what the plan said, and what was done instead;
- why, and who decided;
- whether the results it affects were known when it was decided;
- whether anything was re-run because of it, and whether the result moved.

The first time the analysis writes results, the emitter keeps the plan as it stood in
`design/plan.frozen.yaml`, and never writes it again. Change the plan in `design/plan.md`,
never the frozen copy; a plan changed after that with its Deviations section as it was is
`plan-changed-after-results`, a warning that says the change was not declared.

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
