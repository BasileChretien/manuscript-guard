---
name: manuscript-writing
description: Draft or revise manuscript prose that reads as though a person wrote it. Use when writing any section, when check reports ai-phrasing, ai-cadence or vague-attribution, or when revising text that was drafted quickly.
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

## Checking your work

```bash
manuscript-guard check          # G6 among the rest
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
