# Auditing a paper you already wrote

For a manuscript that was never built this way — no bindings, every number a literal —
there is one command:

```bash
manuscript-guard audit manuscript.docx supplement1.docx \
    --against results/ analysis_output.csv \
    --figures figures/
```

It reads the .docx with **tracked changes accepted** and **table cells kept apart** (Word
stores a row with no separator, so a naive read turns `39 | 20 | 26 | 16` into the single
number 39,202,616 and silently skips every table), drops the bibliography, classifies
conventions and cross-references, and reports every remaining number that appears nowhere
in your outputs.

**It also tells you how little that means.** The report ends with a measurement of the
backing set you supplied:

```
What a match is worth here:
  integers 1-100      100% of all possible values already match
  integers 1-1000     100%
  two-decimal           2%
  A match on a small integer means almost nothing here. Check those by hand.
  Point --against at the analysis outputs rather than the raw data if you can.
```

That measurement is the point. This audit can only ask whether a number appears *somewhere*
in the outputs, and in a previous project that question was measured as near-vacuous: 100%
of integers up to 100 already matched, and of fifteen deliberately corrupted headline
numbers it caught none. A clean audit report is not a clean paper, and the report says so
every time. Use `--strict` to exit non-zero on anything unmatched.

One check needs no outputs. Each t, F, chi-squared or z statistic with a P after it in
its sentence is held to that P: the P the statistic gives is worked out over every value
their printed digits allow, and a P that does not follow is listed apart, with whether it
falls on the other side of 0.05. A one-sided, adjusted or exact test the sentence names
is not judged, and `--strict` does not count these. Each named estimate with a confidence
interval after it is held to it the same way: a ratio whose interval is lopsided on the log
scale, and an interval that excludes its null beside a P above one less its level, or
includes it beside one below, are listed with them.

For a paper still being written, bind the numbers instead — then a stale one is impossible
rather than merely searched for.

[Back to the README](../README.md)
