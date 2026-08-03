---
name: literature-verify
description: Retrieve a source, extract a value with its verbatim quote, and record it so the chain from manuscript to published sentence can be verified. Use when adding a number from the literature, when check reports literature-source-missing or quote-not-in-source, or when a citation needs a stored source.
---

# Recording a number from the literature

A number taken from a published paper is the easiest kind to get wrong and the hardest to
audit later: it arrives by eye, gets retyped, and by the time anyone questions it the tab
is closed and nobody remembers which table it came from.

The ledger fixes that by storing three things together — the value, the sentence that
states it, and the source that sentence came from. Two of the three can then be checked
mechanically: the quote must really appear in the stored source, and the value must really
appear in the quote. Get those right and the chain is verified without anyone re-reading
the paper.

## 1. Get the source

Use the Claude-in-Chrome tools, so the user's institutional session applies and paywalled
full texts are reachable. Save what you can actually read:

- **Full text** — the PDF, or the article page saved as HTML.
- **Abstract only** — when the full text is genuinely unreachable. Save the abstract page.
  This is a legitimate outcome, not a failure; it is recorded as such and never blocks a
  build.

File it under `literature/sources/` named for the citation key, not for whatever the
publisher called the download:

```
literature/sources/smith2020Prevalence.pdf
literature/sources/jones2019Cohort.abstract.txt
```

If PDF text extraction is unavailable, save the relevant passage as a `.txt` beside the
PDF. A source nothing can read cannot have its quote verified, and the check will say so.

Only retrieve what the user's own access permits. Fetch the specific sources the work
needs; do not sweep a publisher's site.

**When you cannot get it at all**, stop and tell the user which source you could not
reach and why. Do not guess the value, and do not write an attestation yourself — see §4.

## 2. Extract the value

Copy the sentence containing the number **verbatim**. Do not tidy it, do not translate it,
do not merge two sentences. The quote is the evidence; an approximation of it is not.

Record where it came from precisely enough for someone else to check without reading the
whole paper: `Table 2, p. 415`, not `Results`.

## 3. Write the entry

In `literature/ledger.yaml`:

```yaml
- key: smith2020.prevalence
  value: 12.4
  display: "12.4"
  unit: "%"
  citekey: smith2020Prevalence          # pinned in Zotero
  depth: full-text                       # or abstract-only
  source_file: sources/smith2020Prevalence.pdf
  locator: "Table 2, p. 415"
  quote: "The prevalence was 12.4% (95% CI 10.1-14.9)."
  verified_on: 2026-08-03
```

The item must be **in Zotero with a pinned citation key**. An unpinned key is regenerated
from metadata, so correcting an author's initials silently renames it and every citation
using it stops resolving.

Then confirm the chain holds:

```bash
manuscript-guard check
```

`quote-not-in-source` means the quote was retyped rather than copied, or the stored file is
not the one it was taken from. `value-not-in-quote` means the sentence quoted does not
actually state the number it is offered as evidence for — usually the quote is the sentence
before or after the one wanted.

## 4. When nobody can retrieve it

Sometimes the user has read something the toolkit cannot store: a printed report, a
withdrawn document, a personal communication. That goes in `literature/attested.yaml`, and
the rules are different because the guarantee is different.

An attestation says **a named person read this and takes responsibility for it**. A model
cannot take responsibility, so it may not sign one — the check rejects an `attested_by`
that names a model, and it is right to.

What you can do is draft the entry and ask the user to confirm it and put their own name
to it. Say what was read, where in it, and why it could not be stored:

```yaml
- key: agency.exposure_estimate
  value: 41200
  display: "41 200"
  source: "National Agency annual report 2019, print edition"
  locator: "Table 14, p. 88"
  statement: >-
    Read from the printed report in the hospital library. The agency withdrew the PDF in
    2021 and no archived copy could be found, so no source file could be stored.
  attested_by: ""        # the user fills this in
  attested_on: 2026-08-03
```

Leave `attested_by` empty and ask. Filling it in on the user's behalf defeats the only
thing the file exists to record.

## What good looks like

Every literature value in the manuscript traces to a sentence in a file on disk, or to a
person's signed statement about something that is not on disk. There is no third category,
and no value that arrived by memory.
