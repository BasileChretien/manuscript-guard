---
name: manuscript-writing
description: Draft or revise manuscript prose that reads as though a person wrote it. Use when writing any section, when check reports ai-phrasing, ai-cadence, vague-attribution, an abbreviation finding (used before defined, redefined, unused, undefined), term-avoided or vocabulary-conflict, or when revising text that was drafted quickly.
---

# Writing prose that reads as written

The lint in G6 catches habits, not authorship. It will flag a person who writes "it is
important to note" and miss a model that avoids every construction on its list. So passing
it is the floor, not the goal. What follows is the goal.

## Say the thing

Most machine-written scientific prose fails in one way: it describes the *significance* of
a finding instead of stating the finding. Every listed tell is a variant of that.

> The reporting odds ratio was elevated, underscoring the importance of continued
> pharmacovigilance for this agent.

The clause after the comma asserts importance and adds nothing checkable. Cut it and put a
number in its place:

> The reporting odds ratio was 3.84 (95% CI 2.89 to 5.12), based on 77 cases.

If a sentence would survive being deleted with nothing lost, delete it.

## The specific habits

**Do not write about writing.** "It is important to note that", "it is worth mentioning",
"notably". If it were not worth mentioning it would not be in the paper.

**Do not use "not just X but Y".** It reads as emphasis and usually says less than X and Y
stated plainly. The same goes for "it's not A, it's B".

**Do not attach an "-ing" tail asserting significance.** "…, highlighting the need for…",
"…, reflecting the broader trend of…". These are almost never true claims; they are the
shape of a claim.

**Use "is".** "Serves as", "stands as", "functions as", "represents a" — occasionally one
of these is the right verb. Usually "is" was.

**Attribute or cut.** "Studies have shown", "experts argue", "it is widely accepted". Which
studies? Cite them. If you cannot cite them, you do not know it.

**Watch the rate, not the word.** "Robust", "crucial", "key", "comprehensive", "highlight"
are ordinary words with legitimate uses. Six of them in a paragraph is the tell. The lint
measures a rate for exactly this reason, and so should you.

**Em dashes are fine in moderation.** So is bold. The lint's thresholds are rates, not
prohibitions.

## The formulaic conclusion

The source essay names a shape that is worth avoiding wholesale:

> Despite these limitations, this study provides valuable insight into … Future research
> should explore … Ultimately, these findings contribute to a growing body of evidence …

Three sentences, no content. A discussion that ends well ends with what the reader should
now believe, and what would change their mind:

> Disproportionality cannot establish incidence, and these data contain no denominator.
> A cohort study with prescription counts would settle whether the excess reflects risk or
> reporting.

## Abbreviations

Define an abbreviation where it first appears, long form first: "the reporting odds ratio
(ROR)". From there on use the short form every time. Do not define it again in the
Discussion, and do not define one the text will not use: if it would appear once or twice,
write it out.

The abstract is read without the paper, so it carries its own definitions and the main
text starts again. A supplement may rely on what the main text defined.

G14 reports the four ways this goes wrong, as warnings:

| Code | What happened | What to do |
|---|---|---|
| `abbreviation-used-before-defined` | the short form appears above its definition | move the definition to the first use |
| `abbreviation-redefined` | it is defined twice, or as two things | keep the first definition; if the meanings differ, give the second its own short form |
| `abbreviation-unused` | it is defined and nothing uses it | write the long form and drop the brackets |
| `abbreviation-undefined` | it is used and never defined | define it at first use |

The check reads capitals, so it also reports names: a trial, a statistics package, an
agency. And some journals let a few abbreviations stand. Those go in `paper.yaml`, written
as the manuscript writes them:

```yaml
language:
  known_abbreviations:
    - "CI"
    - "SAS"
    - "NO"
```

Quote each entry: unquoted, YAML reads `NO`, `ON` and `YES` as booleans, and `check` then
fails on the setting. List one only when the journal's instructions allow it or it is a
name. The list is the author's decision, so ask before adding to it.

A chemical formula with a count in it (`CO2`, `CO~2~`, `NaHCO3`), the unit symbols
shipped (`MHz`, `GPa`) and a registration number (`NCT01234567`) are not reported and need
no entry. A formula with no count (`HCl`, `NaOH`) is reported like any abbreviation.

## One term for one thing

Choose one word for each thing the paper is about and keep to it. "Participants" in the
Methods and "subjects" in the Results reads as two groups, and a reader of a paper is
entitled to assume a new word means a new thing. Varying the word for the sake of style is
the wrong instinct here.

The choice is the author's, and often the field's or the reporting guideline's. Once it is
made, write it into `paper.yaml` with the words it replaces:

```yaml
language:
  vocabulary:
    - use: "participants"
      avoid: ["subjects", "patients"]
      why: The trial's own wording.
```

G14 then reports `term-avoided` for each word given up that the manuscript still uses, in
a sentence or a heading: one finding for the word, at its first use, with how many times
it is used. The finding gives one line and a count, so search the manuscript for the other
uses and change them all. To answer one, use the paper's term. If the word is right where
it stands because it means something else there, the entry is too wide: narrow it, and say
so to the author. `vocabulary-conflict` means two entries disagree about a term; the
author decides which stands.

How a term is matched:

- A term written in the singular is found in the plural too. One written in the plural is
  found only so: give up "subjects", not "subject", or "subject to bias" is reported.
- Only the plural in `s` is folded. For "study" and "studies", list both.
- A word written with two capitals together, `OR`, `WHO`, the `II` of "phase II trial",
  is matched as written, so giving up an abbreviation for its long form does not report
  the word it spells. The other words of a term are found in any case.
- An entry for the singular and one for the plural can stand side by side: "subject" for
  "participant" and "subjects" for "participants".
- A hyphen and a space between a term's words are read as one, so the choice between
  "follow up" and "follow-up" cannot be declared here.
- Quote the terms, as with abbreviations.

When drafting or revising, look for pairs the list does not hold yet: two words for the
outcome, the exposure, the population, the data source or the method. Propose the entry;
do not add it without the author's word, since choosing between two terms is choosing what
the paper says.

## Checking your work

```bash
manuscript-guard check          # G6 and G14 among the rest
```

Findings name the rule and the reason. Disagree freely — several of these constructions
have defensible uses, and the warnings do not block a build. What you should not do is
change a sentence merely to satisfy the lint: if the rewrite is worse, keep the original
and say so.

Two things do block: model output artefacts (`oaicite`, `[cite: 1]`, "as of my last
training data") and unfilled placeholders. Those have no defensible use in a submission.

## If you are a model reading this

Draft freely, then re-read the draft against this page before showing it to anyone. The
constructions above will be in your first draft; that is what the page is for. The specific
thing to check for is the one at the top: sentences that assert importance instead of
stating a result. They are the hardest to notice and the most damaging to a paper, because
a reviewer reads them as padding and a reader learns nothing from them.
