# Writing for every reader

Part of the manuscript-writing skill. Read it when drafting any section, before a review
round, when a clarity reader of the panel has reported (the review-panel skill's
references/remits.md), or when `check` reports `discussion-not-reported`,
`discussion-in-supplement`, `analysis-not-in-methods` or `caption-line-unnamed`.

A paper is read by four kinds of reader its authors seldom are:

- a reader of the field who has not seen this paper;
- a reader who has never studied statistics;
- a reader who looks at the tables and the figures and little else;
- a reader of the abstract alone, who is most of its readers.

Each of them stops at a place the authors no longer see. A panel that checks the numbers,
the consistency and the claims for many rounds does not find those places, because it knows
what every word means. The rules below say what each reader needs. A few of the failures
have a shape `check` can find, and the table at the end says which; the rest are found by
reading, and the panel's clarity remits are how that reading is done and recorded.

## Every term defined where it is first used

A term the paper coins or uses in a sense of its own is defined at its first use, in the
abstract and again in the main text, which does not inherit the abstract's definitions.

- Define the paper's central quantity first, in a clause a reader of the field can follow:
  what is counted, over what, and divided by what. "Persistence, the number of consecutive
  quarters in which the signal met the criterion" is a definition; "signal persistence
  (SP)" is only a short form.
- Define it for every unit it is computed for. A quantity defined per drug and then reported
  per reporter is undefined for the reporter.
- Define a method or a comparison the abstract names in its words: "the strictest of the
  three comparisons" means nothing until the abstract says what is compared with what.
- Describe a group by the property that defines it. A group defined by one property and
  described in the abstract by another, which most of its members have and some do not,
  says something false of those.

G14 holds an abbreviation to its definition; nothing holds the long form to saying what the
thing is.

## One sense for each word

A reader takes a word met again to mean what it meant the first time. A word that names a
thing of the study names that thing only:

- "sample" for the people studied and for a draw of a resampling method;
- "model" for the regression and for the simulated comparison it is held against;
- "control" for the comparison group and for a negative control outcome;
- "random" for chance and for a comparator built by randomising the data;
- "unadjusted" for a model without covariates and for P values not corrected for several
  tests, which can stand in one table.

Give the second sense another word, and once the pair is chosen declare it under `language:
vocabulary:` in `paper.yaml` (the "One term for one thing" section of the skill).

## A plain gloss of each method where it first appears

Each statistical method gets one sentence, or a clause, that says what it does for this
paper's question, in words and no symbols, where the Methods first name it. The Results
repeat the gloss only where a reader meets a result before its method. Glosses that work for
a reader without statistical training:

| Method or term | A gloss |
|---|---|
| odds ratio | 1 means the odds were the same in the two groups; above 1, higher in the first; below 1, lower |
| confidence interval | the range of values the data are compatible with, at the level given |
| an interval in a census | say what it is an interval for: the process that produced the counts, or a population the census stands for; where there is none, give no interval |
| Wilson interval | an interval for a proportion that stays between 0% and 100% and holds for small counts |
| Fisher's exact test | a test of whether two proportions differ that holds for small counts |
| a correction for several tests (Holm, Bonferroni) | each P value is made larger because many were tested, so that one small by chance among many does not pass |
| adjusted for age and sex | compared as though the groups had the same mix of ages and sexes |
| conditioning on X | comparing only units that are alike in X |
| bootstrap, jackknife | the analysis repeated on samples drawn from the data, or with one unit left out at a time, to see how far the estimate moves |
| precision and recall | of the units flagged, the share that were right; of the units that should have been flagged, the share that were |
| expected by chance | what the value would be if the thing studied were assigned at random, with what else is kept as observed said |
| sensitivity analysis | the analysis repeated under another reasonable choice, named, to show whether the result depends on it |

A gloss defined only under a supplementary table is not defined for the reader of the main
text. Every test the Results use is named in the Methods, with what it was used for: `check`
warns of one the Results name and the Methods never do (`analysis-not-in-methods`), from a
list of tests, corrections, intervals and models (`data/statistical_methods.yaml`). The list
does not say whether a gloss is enough; the statistics remit does.

## Numbers a reader can read without the Methods

- **Label every range.** "(95% CI 1.2 to 2.3)", "(range 3 to 17)", "(interquartile range 4
  to 9)", "(2.5th to 97.5th percentiles of 1,000 random draws)". A range after a share
  expected by chance, left bare, is read as a confidence interval of the share.
- **Say why overlapping intervals sit beside a difference.** Two estimates whose intervals
  overlap can differ: the difference has an interval of its own. Where the paper reports both,
  one sentence says so, or the reader concludes there is no difference.
- **Say what a label is worth.** "Exploratory", "post hoc" and "secondary" tell a statistician
  how much weight a result carries; a sentence tells everyone else: "This comparison was not
  planned, and is a question for another study rather than evidence."
- **Say what each sensitivity analysis is for**, before its result: which choice it changes,
  and what the reader should conclude if the result holds or moves.
- **Explain "by construction".** A result said to hold by construction holds because of how a
  quantity was built: say in a sentence which part of the construction makes it so, or the
  reader cannot tell a property of the data from one of the method.
- **Put the headline first, with its size.** The order of a sentence's clauses tells the reader
  what matters. A sentence that opens with a qualifier and ends with the main result reads
  as though the result were the exception; one that gives a small subgroup's figure before the
  whole sample's reads as though the small one were the finding.

## The Discussion interprets what the Results report

Each result the Discussion interprets is reported in the Results first, with its number, so
that a reader meets the result before its interpretation. A result reported only in the
supplement is reported in the Results as well, or pointed at there ("Table S3"). `check`
reads the bindings: a result the Discussion binds that the paper reports nowhere is a warning
(`discussion-not-reported`), and one only the supplement reports a note
(`discussion-in-supplement`). A result the Discussion interprets in words alone, with no
number, is the newcomer reader's to find.

## Displays that stand alone

A table or a figure is read without the text, and the caption, legend and notes are all its
reader has. They say:

- what is shown: the units counted, the population, the period;
- each symbol, abbreviation, column heading and unit that is not plain English, a single
  letter among them: "n/N, cases with the outcome over all cases", "R, the ratio of observed
  to expected reports". G14 holds a display's own definitions to its own uses, and leaves a
  form the text defined to the text's definition; the displays reader holds the display to
  its own;
- which row or series is the comparator, and the one the text's headline uses;
- the test behind each P value, and whether the P values are corrected and how;
- what each line, band and mark stands for, and how it is drawn: "estimates right of the
  dashed line at an odds ratio of 1". `check` warns of a caption that points at "the line" and
  never says which (`caption-line-unnamed`);
- why a total differs from the count the text gives, where it does: "rows are reports; one
  patient may have several";
- one sense for each word in it, and a legend that names what the caption names.

**The figure draws the comparison the text headlines.** Where the text reports a result
against the strictest of several comparators and the figure draws only the weakest, the
figure overstates the result for every reader who looks at it alone. Draw the comparator the
headline uses, or headline what the figure draws. The figure review asks this under
`caption-agrees` (the figure-review skill).

A table's caption the analysis emits (`em.table(..., caption=...)`) is held to the same: write
the symbols, the comparator and the correction into it in the script, where it is kept with
the table.

## The abstract alone

The abstract is read without the paper. It defines every term its reader needs, the central
quantity first; it says against what its headline comparison was made; and it carries the
caveat its conclusion turns on. Each of those costs words, and the journal's limit is
counted by G4 (`over-journal-limit`). Ways to make room:

- define by apposition, in the sentence that uses the term, rather than in a sentence of its
  own: "the reporting odds ratio, the odds that a report names the event for this drug
  against all other drugs, was ...";
- give the headline's estimate with its interval, and drop the secondary results before a
  definition the headline needs;
- cut the background to the one sentence that says what was not known.

Then have the abstract read alone again (the review-panel skill's abstract-alone remit): a
definition added can still leave the sentence unreadable to someone who has only it.

## What `check` finds, and what it leaves to readers

| Defect | Found by |
|---|---|
| a result the Discussion binds that the paper reports nowhere, or only in the supplement | G8, `discussion-not-reported` (warning), `discussion-in-supplement` (note) |
| a test, correction, interval or model the Results name and the Methods never do, from a list | G9, `analysis-not-in-methods` (warning) |
| a caption that points at "the line" or "the curve" and never says which | G3, `caption-line-unnamed` (warning) |
| an abbreviation used before or without its definition, a display's own included | G14 |
| a term used before it is defined, or in two senses; a group described against its definition | the newcomer and abstract-alone readers |
| a method with no plain gloss; an unlabelled range; overlapping intervals unexplained; a label's weight unsaid | the plain-statistics reader |
| a display that does not stand alone; a figure that draws a weaker comparison than the text headlines | the displays-alone reader, and the figure review's `caption-agrees` |
| a headline whose size the clause order hides; "by construction" unexplained | the newcomer reader |

The warnings are advice: each reads a shape, and a shape can be right where it stands. Where
it is, leave it, and say so to the author.
