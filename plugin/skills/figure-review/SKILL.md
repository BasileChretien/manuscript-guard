---
name: figure-review
description: Look at a rendered figure and record whether it is honest, complete and consistent with the results and the manuscript. Use when `manuscript-guard check` reports figure-unreviewed or figure-review-stale, after re-rendering a figure, or before a submission build.
---

# Reviewing a figure

There is a class of error in figures that no parser reaches. A truncated axis that makes a
small difference look decisive. A legend naming a series the plot no longer contains. Two
panels drawn at different scales and set side by side. A caption describing the figure the
author meant to make. Every number can trace back to the results and the picture can still
mislead.

That is the gap this skill fills, and it is why the review must be done by **looking at the
rendered figure**, not by reading its source. Reading the script tells you what the author
intended to draw; only the image tells you what a reader will see.

## Before you start

Run `manuscript-guard check` and note which figures are unreviewed or stale. Then, for each
one, gather three things: the rendered figure, the results values it should be showing, and
the manuscript passage that refers to it.

```bash
manuscript-guard check --json          # which figures need a review
```

Read the raster export if there is one — a PNG or TIFF beside the vector file. It is what a
reader sees, and it exposes crowding and clipping that the vector source hides. If only a
vector exists, render one; do not review a figure you have not seen.

## What to check

Seven checks, all required. Recording one as passed without a note is the same as not
having done it, so write what you actually saw in each case.

| id | The question |
|---|---|
| `values-match-results` | Does every number shown match `results/`, to the digit? Do the marks sit where those values belong on the scale? |
| `axes-labelled-and-scaled` | Do axes carry units? Is a log or truncated scale declared rather than left to be inferred? |
| `caption-agrees` | Does the caption describe the figure that is actually drawn — the same panels, the same series, the same comparison? |
| `legend-and-marks-explained` | Is every mark, colour, line style and series accounted for? Is anything drawn that nothing names? |
| `no-unexplained-number` | Is anything visible that is neither a result nor part of the scale? |
| `scale-not-misleading` | Does the visual encoding overstate the finding? Baseline not at zero, area used for a linear quantity, a ratio on a linear axis? |
| `readable-and-accessible` | Legible at print size? Does any information depend on colour alone? |

The check that most often finds something is `caption-agrees`, because the text and the
figure are edited at different times and drift apart quietly. Read the manuscript sentence
that refers to the figure and compare it, word by word, against what is drawn. A sentence
promising "against the comparators" beside a single-row plot is the archetype.

## Recording it

Once you have looked at the figure, have the toolkit start the record:

```bash
manuscript-guard review --record-figure forest --by "<who looked at it>" --verdict pass
```

That writes `figures/<name>.review.yaml` with the figure's content digest, which has to be
the toolkit's and not a plain file hash, because it deliberately ignores render metadata and
generated element ids. It also lists all seven checks as `ok: false`, each with the question
it asks, so the file is a to-do list. `--by` is required, because the record's whole content
is that a particular person or model looked at a particular rendering. The verdict is `pass`
or `concerns`. The command refuses to overwrite a record; to record a fresh reading, delete
the old file first.

Then finish the file by hand. Set each check to `ok: true` and replace its question with what
you saw. A check left `ok: false` fails the gate, and the gate names each one.

```yaml
schema: manuscript-guard/figure-review/1
figure: forest.svg
content_sha256: <written by the command>
reviewed_by: <your model identifier, or a person's name>
reviewed_on: <YYYY-MM-DD>
caption_checked_against: manuscript/main.md    # optional, not written by the command
verdict: pass          # or: concerns
checks:
  - id: values-match-results
    ok: true
    note: What you saw, specifically.
  # ... all seven
findings:              # optional, not written by the command
  - severity: warn     # fail | warn | info
    message: What is wrong and what would fix it.
    where: Which part of the figure.
```

`verdict: concerns` fails the build. Use it when something must change before submission.
Use a `warn` finding for something a reader should know about that does not block.

When one figure is exported in several formats, review it once: the record belongs to the
preferred file, vector before raster, and covers all of them.

## Honesty

The gate enforces that a review exists, that it covered all seven checks, and that it
applies to the figure as it now stands. It cannot tell whether the review was any good.
A review recorded without looking is worse than no review, because it converts an
unexamined figure into one the build calls examined. If you cannot see the figure, say so
and stop; do not record a review from the source code.
