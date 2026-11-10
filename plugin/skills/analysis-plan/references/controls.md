# Controls the plan declares

An analysis that has only been run on the study's data has never shown that it can find an
answer. A control shows it, put through the same analysis by the same script: data
simulated with a known effect; a positive control, an association known to exist; or a
negative control, an exposure or an outcome for which no effect is expected (Lipsitch et al.,
*Epidemiology* 2010;21:383-8). Choose them now: a control chosen once the results are known
shows much less, and the plan's frozen copy says which it was.

Declare them in one fenced `yaml` block anywhere in the plan, not under the Deviations: one
`controls:` list with an entry for each, since a second block that declares controls is
refused whole. In a case-control plan, keep the word "control" out of the heading above it:
G12 would read that heading as the plan's section on how the controls are selected.

```yaml
controls:
  - key: control.headache        # what em.control() emits it under
    kind: negative                # simulated, positive or negative
    of: ror.*                     # the result it stands beside
    expected: 1                   # the value planted, the association known, or the null
    rule: holds-null              # holds-expected, holds-null, or within with a distance
```

`holds-expected` passes when the interval holds the expected value, `holds-null` when it
holds the null (0 for a difference, 1 for a ratio), and `within` when the estimate is no
further than `distance` from it, on the scale the analysis emits. A simulated control that
plants no effect, the exposure shuffled, expects the null. A control held to its expected
value, by `holds-expected` or `within`, also names its null, `null: 1` for a ratio or
`null: 0` for a difference. Where it expects an effect, a positive control or a simulated
one that plants it, its interval must leave that null out, or it fails: a control that
would pass an analysis finding nothing shows nothing. Choose a positive control whose
expected value lies far enough from the null for the interval to leave it out, a known
reaction strong enough that missing it would say the analysis is broken. The script that
writes the result `of` names emits the control, `em.control(key, estimate, lower, upper)`
(the [results-binding](../../results-binding/SKILL.md) skill), and the paper reports each
one, in the Methods, the Results or the supplement.

G12 holds the plan to what was emitted: a control that fails its rule, one never emitted,
one chosen after the first results or changed since, one the plan does not declare, one run
by another script than its result's, and one the paper does not report. Each warns, and
fails at submission. A failed control is reported, and the Deviations say why, naming its
key: it then stays a warning at submission, since a control that failed in the open is a
finding of the study. A missing, late or changed one is said under the Deviations, naming
its key. A control added after a first run on synthetic data alone is late only in a note,
since that run dated no real result. No design requires a control. Some to consider:

| Design | Controls to consider |
|---|---|
| cohort, case-control | a negative control outcome the exposure could not cause, or a negative control exposure that shares the biases and has no effect |
| self-controlled | a negative control outcome, with the same risk windows |
| disproportionality | drug-event pairs with no known association; a known adverse reaction of a drug in the database as a positive control |
| trial, systematic-review | data simulated with a known effect, through the analysis code |
| prediction-model | data simulated with a known structure, and the held-out data of [held-out.md](held-out.md) |
