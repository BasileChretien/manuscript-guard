# Words beside an interval

Part of the manuscript-writing skill, read when `check` reports `claim-beyond-interval`,
`significance-beyond-interval` or `no-effect-from-interval`.

G8 reads the words of each sentence that prints an estimate with its confidence interval.
Where the interval includes no effect, 1 for a ratio and 0 for a difference:

- `claim-beyond-interval`: the sentence states an effect or a difference with no hedge,
  "increased the risk", "was associated with a higher risk". The data are compatible with
  no effect at all. Say what was estimated and what the interval allows: "the hazard was
  31% higher (HR 1.31, 95% CI 0.92 to 1.86), and the interval includes no difference".
- `significance-beyond-interval`: the sentence calls the estimate significant. At the
  paper's level it is not. If the test said it was, the interval or the P comes from
  another analysis, and that is settled in the analysis, not in the sentence.
- `no-effect-from-interval`, a note: the sentence says there is no effect, while the
  interval does not exclude ratios above 1.5 or below 1/1.5. The study did not show that
  nothing happens; say which effects the interval leaves open, or call the result
  inconclusive.

None is said where the sentence hedges, calls its interval profile-likelihood, exact,
bootstrap or Bayesian, says the difference was not significant, or names another test
("P for interaction", "test of heterogeneity"). "No significant difference" speaks of the
test and is left alone.
The words are read from lists, so a sentence can be reported for a word about something
else: "patients who had reduced renal function" reads as a difference stated. Where the
words are right, leave them; the findings are a warning and a note, and block nothing.
