---
name: methods-review
description: Learn from the methods of studies of the same question before the analysis plan is settled - find them, record each method in the study's own words, judge it against a published methodological standard, and let the author decide what the plan takes, with its citation. Use at the design stage, when choosing a comparator, a time zero, a case definition or an adjustment set, or when check reports similar-passage-not-in-source, similar-passage-unchecked, similar-passage-too-short, similar-decision-not-human, similar-unappraised, similar-undecided, appraisal-without-standard, appraisal-standard-unknown, appraisal-domain-unknown, standard-redescribed, adopted-method-uncited or adopted-standard-uncited. Not for writing the plan itself (use analysis-plan).
---

# Learning from how others answered the question

A plan is better for knowing how others answered its question: which comparator they chose,
when they started follow-up, how they defined the outcome, what they adjusted for. It is not
better for doing what most of them did. A design used often can carry a bias often: immortal
time, follow-up counted as exposed before the exposure began, was found in one published
study of drug effects after another (Suissa, *Am J Epidemiol* 2008;167:492-499). So each
method is judged against a published methodological standard, never by how many studies
used it, and the author decides what the plan takes.

The record is `design/methods_review.yaml`. The worked example has one; its study is
invented.

## 1. Find the studies

Say first what makes a study similar to this one: the same question, exposure, outcome,
population, data source or design. Then search, once for each of those that matters:

```bash
manuscript-guard search "drug-induced liver injury case definition"
```

`search` proposes works from PubMed, Europe PMC and OpenAlex; it writes nothing, and the
author chooses. Never name a study from memory. How many is the author's choice: the most
relevant five to ten is usually enough, the closest on question and data source first, and
nothing counts them. Record each search under `searched:` (`with`, `query`, `searched_on`,
`found`), so that a reader can repeat it.

The author adds each chosen study to Zotero (Add Item by Identifier), with a pinned
citation key. Then:

```bash
manuscript-guard sync-sources
```

copies each study the review names into `literature/sources/`, as it copies the works the
manuscript cites; `--from <folder>` takes PDFs a downloader saved, named by DOI, for a study
that is in `references.bib`. A passage is checked against that copy, and against nothing
else.

## 2. Record each method in the study's words

One entry per study: its `citekey`, what it shares with this study (`similar`: question,
exposure, outcome, population, data source, design) and `why` it was chosen. Under
`methods`, one entry per field the study reports:

| Field | What to copy |
|---|---|
| design | the design, as the study names it |
| data source | the database, registry or cohort, its version and period |
| population | inclusion and exclusion |
| case definition | how a case was counted |
| exposure | the definition as coded, and how exposure time was assigned |
| outcome | the definition, and whether it was validated |
| comparator | what the exposed were compared with |
| time zero and follow-up | when follow-up began and ended, and why then |
| confounding | the adjustment set, and how it was chosen |
| model | the estimator and the model |
| missing data | how missing values were handled |
| sensitivity analyses | which, and what each tested |
| other | anything else, with a `label` |

Each entry has the `passage`, copied from the stored copy word for word (words left out
marked `[...]`), and a `locator` precise enough for a co-author to find it: "Methods,
Exposure, p. 3". A `summary` of a few words is for the table. G7 looks for every passage in
the study's stored files; one that is not there fails once the analysis runs
(`similar-passage-not-in-source`). A field the study does not report has no entry: what it
leaves unsaid can be said in an appraisal of a field it does report.

## 3. Judge each method against a standard

An appraisal names the standard (`standard`, by id), the standard's domain the judgement
is of (`domain`, as the standard names it), how far the method departs from it (`concern`:
low, some, serious or unclear), what the risk is (`says`), and who proposed it
(`proposed_by`, `proposed_on`). An agent may propose one. Several standards may bear on one
method: `appraisal` may be a list.

The built-in standards are in the package's `data/method_standards.yaml`, each with its
domains, where it is published and the date it was read. By design:

| Design | Standards (ids) |
|---|---|
| cohort | `target-trial`, `robins-i`, `robins-e`, `immortal-time`, `encepp-guide`, `strobe`, `record-pe` |
| case-control | `target-trial`, `robins-i`, `robins-e`, `immortal-time`, `encepp-guide`, `strobe`, `record-pe` |
| self-controlled | `sccs`, `robins-i`, `encepp-guide`, `record-pe` |
| disproportionality | `readus-pv`, `encepp-guide` |
| trial | `rob-2` |
| prediction model | `probast-ai` |
| systematic review | `robis`, `encepp-guide` |

A standard the table does not hold is described under `standards:` with its `id`, `name`,
`domains` and `citekey`. A built-in one is given only its `citekey` there, the key the plan
cites it under.

Writing a judgement:

- Read the standard's domain before judging against it: add the standard to Zotero too and
  give it its `citekey`, so that `sync-sources` stores it. A standard recalled is a standard
  misquoted.
- Name the mechanism, not a verdict: "risk of immortal time: exposure is defined from a
  dispensing after cohort entry, so the exposed are counted at risk before they were
  exposed", against `target-trial`, `Follow-up period`, not "the design is weak".
- "Five of seven studies did this" is not an appraisal. Agreement among studies is not
  evidence that a method is sound.
- Record the methods with low concern too: they are what the plan may take.
- Where the stored copy does not say enough to judge, say `unclear` and what is missing.

G12 warns where an appraisal names no standard (`appraisal-without-standard`), one nothing
holds (`appraisal-standard-unknown`), or no domain of it (`appraisal-domain-unknown`). It
does not check that the judgement is right, and cannot: that is what the design round and
the author are for.

## 4. The author decides

Put the table to the author: each study, each method, its words and its appraisals. For
each method they decide, they record:

```yaml
        decision:
          choice: adapt            # adopt | adapt | reject
          why: the enzyme criterion only, where a report gives it
          decided_by: "A Person"
          decided_on: 2026-10-21
```

`adapt` says in `why` what is changed. A decision is the person's: G12 refuses a model's
name in `decided_by` (`similar-decision-not-human`), and the write hook puts to the person
any edit that records, removes or changes a decision, or changes the method it was of. The
methods appraised and not decided are counted (`similar-undecided`).

## 5. Take a method into the plan, with its citations

Write the method into the plan's matching section of `design/plan.md` (the
[analysis-plan](../analysis-plan/SKILL.md) skill), and cite where it came from: the study,
`[@smith2020]`, and the methodological source it was judged by, `[@hernan2016]`, which the
review names under `standards:`. G12 warns where a method decided `adopt` or `adapt` is
cited in neither the plan nor the manuscript's Methods (`adopted-method-uncited`), and
where its standard is not (`adopted-standard-uncited`). Credit goes to the study that
applied the method and to the source that sets it out.

When the Methods are drafted, the citing sentence there is a cited statement like any
other: its supporting passage goes in `literature/passages.yaml`, and the review's passage
is usually the one to copy.

## 6. The design round reads it

`manuscript-guard review --design --run` sends the record with the plan: each study, each
method in its words, the appraisals and the decisions. The digest a design reading is filed
with holds the record's bytes, so an appraisal or a decision changed after a reading leaves
it stale, as a changed plan does. A methodologist's remit can ask them to check each
appraisal against its standard, and to say where a method the plan takes carries a risk the
appraisal missed.

## If you are a model doing this

- Propose; do not decide. Never write `decided_by` or a `decision`, and never change a
  method under one.
- Copy passages from the stored copy, never from an abstract, a summary or memory. A study
  with no stored copy has no passage yet: say so.
- Name the standard and the domain of every judgement. If none fits, say so to the author
  instead of writing an impression.
- Do not rank methods by how often they appear, and do not present the most common one as
  the safe choice.
