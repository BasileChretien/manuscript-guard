---
name: reporting-checklist
description: Retrieve a reporting guideline's official checklist (STROBE, CONSORT, PRISMA, RECORD, SPIRIT, TRIPOD, ARRIVE and others) and record it so the build can check that every item is addressed. Use when check reports checklist-not-retrieved, or when adopting a new guideline.
---

# Retrieving a reporting checklist

**No official checklist ships with manuscript-guard, and none should be written from
memory.** Item text that is approximately right produces confident coverage of the wrong
things, which is worse than having no checklist at all — and it would be an odd thing to
put inside a toolkit whose whole argument is that approximately right is not good enough.

So a checklist is retrieved from the guideline's own material, stored, and transcribed from
the stored copy. The transcription can then be checked against the original the same way a
literature quote can be checked against its source.

## 1. Get the official document

Guidelines publish their checklists in different places, and the item text is often not on
the web page at all:

- **STROBE** — `strobe-statement.org`, as PDF and Word per study design. The 2007 statement
  papers carry the checklist as a table, sometimes as an image.
- **CONSORT**, **SPIRIT**, **PRISMA**, **TRIPOD**, **ARRIVE** — each has its own site, and
  all are indexed on the EQUATOR Network, `equator-network.org`.
- **RECORD** and **RECORD-PE** — extensions of STROBE; you need both the STROBE items and
  the extension items.

Download the official file into `profiles/reporting/sources/`. If the checklist is only
available as a scanned table or an image, say so and ask the user for a copy they can read;
do not reconstruct it.

## 2. Transcribe the items

Copy each item's text **verbatim** from the stored document. Keep the guideline's own item
numbering, including sub-letters like `6a`, because that is what journals and reviewers
refer to.

`profiles/reporting/<NAME>.yaml`:

```yaml
schema: manuscript-guard/reporting/1
name: STROBE
long_name: "Strengthening the Reporting of Observational Studies in Epidemiology"
version: "v4 (2007)"
source_url: https://...
source_file: sources/STROBE_checklist_v4_cohort.pdf
retrieved_on: 2026-08-03
applies_to: "Cohort studies"
licence: "..."                 # record it; several are CC-BY-NC-SA

items:
  - id: "1a"
    section: "Title and abstract"
    topic: "Study design"
    text: "<verbatim recommendation text>"
```

Where a checklist gives different wording per study design, either make one file per design
or use each item's `applies_to`. One file per design is usually clearer.

## 3. Answer it

```bash
manuscript-guard checklist STROBE     # writes reporting/STROBE.yaml, one row per item
manuscript-guard check
```

Every item then needs either a `where` — the section that addresses it, checked against
the manuscript's real headings — or a `not_applicable` reason. **"n/a" is rejected.** The
gate wants a reason a reviewer could read: *"no interventions were assigned"*, not a tick.

Re-running `checklist` after a guideline revision preserves the answers already given and
adds only the new items.

## Why this is worth doing early

A reporting checklist filled in the night before submission is filled in backwards, by
searching the manuscript for something that could count as each item. Filled in while
writing, it does the opposite: it tells you what is missing while there is still time to
add it. That is the entire value of the instrument, and it is lost by doing it last.
