---
name: methods-writer
description: Write or reconcile a Methods section against the analysis code that was actually run. Use when drafting Methods, when check reports methods-drift or methods-never-reconciled, or after the analysis changes.
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

## Locking the parameters worth checking

`methods.lock` can carry parameters that must appear in the prose:

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
