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
is not judged, and `--strict` does not count these. A number written with a middle dot or a
comma for its point, "0·62", is not read, so such a paper has none of its tests judged. Each named estimate with a confidence
interval after it is held to it the same way: an estimate outside its own interval, a
ratio whose interval is lopsided on the log scale, and an interval that excludes its null beside a P above one less its level, or
includes it beside one below, are listed with them.

A table's n (%) is held to the denominator the table names for it, the count's own
("12/40 (30.0)") or the "n = 1200" of its column's header: 300 of 1200 is 25.0%, and a table
that prints 300 (26.0) is listed, with the denominators 26.0% of 300 would fit. Half a unit
in the share's last printed place is allowed. Only a column of shares is read: a "%" in the
cell, or "n (%)" in the row's label, the label over its rows or the column's header, says
so, or the shares of a characteristic's categories add up to 100. A row that names a mean,
a median, an SD, an IQR or a range is never read, nor a whole number up to 100 with no "%"
in a row whose label ends on a unit in percent ("Oxygen saturation, %"). A share of its row's own total, where the row's shares add
up to 100, and a share of its categories' own total, where they do, are not listed: a
subtype of another row, or a share of those with data. A row whose label carries a footnote
marker is listed as uncertain, since a note may give it another denominator. Pipe tables are
read in Markdown, and every table in a .docx.

A mean of whole numbers, answers on a Likert-type scale or a count, is a whole total over
its n, so not every mean can be printed for it: 28 answers average 3.46 or 3.50, never 3.47
(the granularity test of Brown and Heathers, 2017). Nothing in a paper says its numbers are
whole, so this is read only in the rows you name. `--whole-numbers "pain score" visits`
reads each table row whose label holds one of those, at word edges and in any case, and
holds each mean in it (alone, with its SD in brackets, or with ± and its SD) to the n of
its column's header. A mean that no whole total over n gives is listed with the other
disagreements, with the totals either side and the n it would fit, since a mean of those
with data has a smaller n than its column. A mean for whose n every mean printed to its
places is possible is listed apart as not assessable: so for 100 numbers or more at two
places, and for 80 and 96. A label under which no mean was read is said. A row whose label
carries a footnote marker or an n of its own is uncertain. Means in sentences are not read.
A mean of several items per person is read as a mean of one number each, so a mean that is
right for its items can be listed: name only rows of one number per person, or quote the
value in the literature ledger, which takes both (`mean_of_whole_numbers: {n: 28, items:
3}`).

For a paper still being written, bind the numbers instead — then a stale one is impossible
rather than merely searched for.

[Back to the README](../README.md)
