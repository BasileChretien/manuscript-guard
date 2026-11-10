# The controls of the analysis

## Methods

Three controls were put through the same 2 x 2 table and interval, by the same script; they
were chosen after the first results were known, as the analysis plan records. A simulated
control drew reports as the database's are drawn, with hepatic injury planted for
example-drug at twice the odds of the other drugs, and its interval was to hold the ratio
planted. A positive control took the third comparator and hepatic injury, which the data
generator makes rarer with that drug than with the others, so that its rates give a ratio
well below one; its interval was to hold that ratio. The interval of each was also to leave
out one, the null, so that an analysis finding nothing would fail them. A negative control
took the first comparator and nausea, for which those rates give a ratio close to one, and
its interval was to hold the null. {{method.controls}}

## Results

The ratio of the simulated control was {{results.control.simulated.point}} (95% CI
{{results.control.simulated.ci_low}} to {{results.control.simulated.ci_high}}), around the
ratio planted; that of the positive control {{results.control.positive.point}} (95% CI
{{results.control.positive.ci_low}} to {{results.control.positive.ci_high}}); and that of
the negative control {{results.control.negative.point}} (95% CI
{{results.control.negative.ci_low}} to {{results.control.negative.ci_high}}).
