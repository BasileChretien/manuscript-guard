---
name: methods-writer
description: Write or reconcile a Methods section against the analysis code that was actually run. Use when drafting Methods, when describing a statistical model, when pointing Methods text at a step of the code, when check reports methods-drift, methods-never-reconciled, a method-… finding or a G15 model-… or variable-… finding, or after the analysis changes.
---

# Writing Methods that describe what was done

Methods sections go stale in a particular way, and it is nobody's fault. The analysis is
written, the Methods are written to match, and then the analysis changes — a filter added,
a model swapped, a threshold moved. Nothing forces the prose to follow, and no one re-reads
their own Methods once they are written. The paper ends up describing an analysis nobody
ran.

G9 does not read the code and judge the prose; nothing can. It records that a person read
the Methods against the analysis, and tells you when the analysis has changed since. This
skill is what to do when it does.

## Writing them the first time

**Read the code, not your memory of it.** Work through the analysis scripts in order and
write down what each actually does. The gap between what an author intended and what the
code does is where Methods sections go wrong, and it is invisible from the manuscript.

For each script, capture what a reader needs to reproduce it:

- what was read, and how records were selected — the actual filter conditions
- how variables were derived, including every recode
- what was excluded, at which stage, and how many
- the estimator, and the assumption it rests on
- every parameter that was chosen rather than estimated
- software and version

**Numbers in the Methods are bindings like any others.** A cohort size, a study period, a
count excluded at each step — all of those come from `{{results.…}}`. If a number in the
Methods is not bound, the analysis is not emitting something it should. Add the emit.

**Write it as a person describing work, not as a specification.** Past tense, active where
it reads naturally. "We removed duplicate reports by matching on report identifier" beats
"Duplicate report removal was performed utilising identifier-based matching". The
[manuscript-writing](../manuscript-writing/SKILL.md) skill covers the register.

## Reconciling after a change

`check` names the files that changed:

```
[FAIL] G9 methods.lock
       the analysis changed after the Methods were last reconciled with it
       > changed: analysis/01_disproportionality.py
```

Read *those* files against the Methods — not the whole analysis, which is why the finding
names them. Then decide, for each change:

- **The change affects what the paper claims** → update the Methods, and check whether any
  Results number moved with it.
- **The change is internal** — a refactor, a comment, faster code with identical output →
  the Methods stand.

Either way, record that you looked:

```bash
manuscript-guard methods --reconcile
```

**Do not run that command merely to clear the finding.** The file's only content is the
claim that a person read the code. Reconciling without reading makes it a lie, and a
lie that is machine-checkable is worse than no check at all, because it will be trusted.

## Pointing each paragraph at the step it describes

A whole file is a coarse thing to have read. Mark the steps of the analysis that the Methods
describe, and end the text that describes each one with an anchor that prints nothing:

```python
with em.step("ci"):                       # R: em$step("ci", { ... })
    se = math.sqrt(1 / a + 1 / b + 1 / c + 1 / d)
    low = math.exp(math.log(ror) - z * se)
```

```markdown
Confidence intervals were derived from the standard error of the log odds ratio.
{{method.ci}}
```

The anchor claims the text before it, back to the anchor before it or the start of its
paragraph. Put it at the **end of the paragraph** where you can: give each step its own short
paragraph. A co-author's edit in Word then comes back with the anchor in place, and an edit to
a paragraph with an anchor in the middle is refused and has to be made in the .md. Two anchors
side by side claim the same text. Write the step's name out in the `with` statement; a step in
a branch the run does not take is not recorded, and an anchor naming it fails.

An anchor prints nothing, but its line stays: a line that holds nothing but anchors prints as
an empty line, and an empty line ends a paragraph. So inside a paragraph, put the anchor at the
end of the sentence's line, not on the line under it. On a line of its own it belongs only
after the paragraph's last line. `check` warns of one inside a paragraph
(`method-anchor-line`); if a new paragraph or a list is meant there, leave a blank line after
the anchor. Keep anchors out of headings, where they claim nothing and are not checked, and off
a line that holds only a quotation's `>` or a list's `-`.

`manuscript-guard methods --explain` lists every claim beside the lines of its step, the
Methods paragraphs that point at no step, and the steps nothing describes. Read each claim
against its lines. When the claim and the code agree, record that pair:

```bash
manuscript-guard methods --reconcile ci       # this step's pairs only
manuscript-guard methods --reconcile          # every pair, and every file
```

Either may come first. Once one pair is recorded, every pair nobody has read is reported as
never read, and `methods-never-reconciled` stays until the second command has been run, which
is the one that says the files were read. For a project in another folder, name it before
the option: `manuscript-guard methods path/to/project --reconcile ci`.

From `internal-review`, `check` fails a pair whose code changed (`method-step-changed`), whose
text changed (`method-claim-changed`, which says what it was) or which was never read
(`method-pair-unread`), and names the paragraph to read again. A pair whose code and text both
changed is reported as never read. A comment or a re-wrapped line inside a step changes
nothing. `method-step-unknown` is an anchor naming no step the run recorded;
`method-step-undescribed` is a step no text points at, and `method-anchor-line` an anchor's own
line inside a paragraph, both warnings. The same rule holds as for the whole
file: reconcile a pair after you read it, never to clear the finding.

## Declaring the choices the code makes

A threshold, a confidence level, a minimum number of cases: these are choices made in the
code and stated in the Methods, and typed in the Methods they pass as conventions, so they
stay behind when the code changes. Declare them in the analysis and bind them:

```python
alpha = em.parameter("alpha", 0.05)          # use the returned value in the computation
min_cases = em.parameter("signal.min_cases", 3)
em.software("statsmodels")                   # the version this run imported
```

```markdown
two-sided at an alpha of {{results.param.alpha}}, and at least
{{results.param.signal.min_cases}} cases. Analyses used statsmodels {{results.software.statsmodels}}.
```

G2 then fails the value typed instead of bound, and fails a parameter the script never reads
again. That second check is the one that matters most: a parameter declared and bound, and
applied nowhere, prints the right number for a step the code does not take. What it cannot
tell is whether a value that is read changes a result; that is still your reading.

A coding dictionary is declared the same way, with its release: MedDRA from the
`meddra_release.asc` of the release the analysis coded with, any other as the script states
it. The file named is digested as an input, so a new release shows as a change.

```python
em.dictionary("MedDRA", release_file="data/MedAscii/meddra_release.asc")
em.dictionary("WHODrug", "Global B3 March 2025")
```

```markdown
Events were coded with MedDRA version {{results.dictionary.meddra}} and drugs with WHODrug
{{results.dictionary.whodrug}}.
```

G2 fails a declared release typed beside the dictionary's name (`typed-dictionary-release`).

## Describing a model

Record the model from its fit and declare every variable it reads, in the analysis:

```python
em.variable("age_group", "categorical", label="age group",
            levels=["18-44", "45-64", "65-74", "75+"], reference="18-44", values=data["age_group"])
fit = smf.glm("hepatic ~ exposed + C(age_group, Treatment('18-44'))", data,
              family=sm.families.Binomial()).fit()
em.model("adjusted", fit, name="Adjusted model", description="What the model is for.")
```

(R: `em$variable(...)` and `em$model("adjusted", glm(...), name = ...)`.) The kind a variable
is declared is the one thing the data cannot tell G15: an ordinal grade and a nominal code
are both integers. Declare what the variable means, not what its storage is.

A comparison written in the formula, `I(stage == 'IV')` or `I(age >= 65)`, is a binary term
of its own: declare the variable it reads as what that variable is, and G15 does not hold the
comparison to its levels or its reference. A comparison inside another call
(`C(stage == 'IV')`, `np.where(...)`, `ifelse(...)`) is not known for one. Derive that
variable before the fit and declare it as a variable of its own.

For grouped data, where a row is a group with its events and its trials
(`"cases + others ~ ..."` in statsmodels, `cbind(cases, others) ~ ...` or a proportion with
`weights` in R), declare the columns of counts as `count`. The card then holds the events and
the trials the table adds up to, and `{{results.model.adjusted.events}}` and
`{{results.model.adjusted.trials}}` bind them.

Then, in the Methods, name the model by binding `{{results.model.adjusted.kind}}`, and place
`{{table.model_adjusted}}` (in the supplement if the journal is short of tables): the outcome
and each variable with its declared kind, how it entered and its reference. If the model
dropped rows for missing values, bind `{{results.model.adjusted.n_dropped}}` where the Methods
say how missing data were handled.

The binding is for the kind that was fitted. A word that leaves the model what it is goes
before the binding: "multivariable {{results.model.adjusted.kind}}", "modified
{{results.model.adjusted.kind}}". A name that says another model, "conditional logistic
regression" or "mixed-effects logistic regression", is typed as it is: G15 does not read a
name after such a word, and `src/manuscript_guard/data/models.yaml` lists the words.

`manuscript-guard models` prints each model as its card. Read it before writing the
paragraph, and give it to a co-author: the author's description beside the sentence made from
the fit is where a model that answers a different question shows.

What G15 reports, and what to do:

| Code | Ask |
|---|---|
| `model-outcome-kind` | the model is not for this kind of outcome: fit one that is, or declare the outcome's real kind |
| `model-categories-as-number` | a categorical variable entered as one slope: enter it as categories |
| `model-binary-as-number` | a binary variable entered as a number and coded otherwise than 0 and 1, or true and false: enter it as categories, or recode it |
| `model-reference`, `model-level-undeclared`, `variable-level-undeclared` | the fit and the declaration disagree about levels: fix whichever is wrong |
| `variable-not-binary` | a variable declared binary takes more than two values in the data: declare the kind it is, or derive the binary variable the model means |
| `model-variable-undeclared` | declare it with `variable()` |
| `model-not-converged`, `model-empty-level` | a sparse level or separation: merge levels or refit, and say what you did |
| `model-rows-dropped` | bind the number dropped where missing data are described |
| `typed-model-kind` | the Methods type the kind of the model fitted: bind `{{results.model.<key>.kind}}` |
| `model-ordinal-as-trend`, `model-number-as-categories`, `model-few-events`, `model-kind-unfitted` | warnings: say in the Methods why, or change the model |
| `model-engine-unknown` | a warning: the toolkit's list has no name for this fit, so its outcome is not checked and it has no kind to bind; name the model in your own words |

## Locking the parameters worth checking

For a value that is not computed by the code (a software version from outside Python or R,
for instance), `methods.lock` can carry parameters that must appear in the prose:

```yaml
parameters:
  alpha: "0.05"
  software: "R 4.6.0"
  estimator: "reporting odds ratio"
```

Each is checked against the Methods text. It is a small check — presence, not correctness —
but the significance threshold and the software version are exactly what a reviewer queries
and exactly what gets left behind when an analysis is redone.

## What this cannot do

It cannot tell you the Methods are right. It tells you when they were last checked and by
implication when they were not. Everything else is your reading.
