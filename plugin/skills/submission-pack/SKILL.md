---
name: submission-pack
description: Assemble everything a journal asks for and write the covering letter. Use when a manuscript is ready to submit, or when check --submission is close to clean and you want to see what remains.
---

# Assembling a submission

A submission is not one file. It is the manuscript, a title page carrying what the
manuscript deliberately omits, a CRediT statement, the declarations, the completed reporting
checklist, the figures in the publisher's format, and a covering letter.

Assembling that by hand at the end is where the last mistakes are made: the title page lists
an author who left two revisions ago, the funding statement contradicts the
acknowledgements, the checklist points at a section that was renamed. Everything except the
letter is already recorded in the project, so `manuscript-guard submit` generates it rather
than asking you to write it twice.

```bash
manuscript-guard check --submission    # everything outstanding, in one list
manuscript-guard submit --offline      # assembles build/submission/
```

The pack will not assemble while the submission check fails. That is the point of having
the check: the pack is the version you send anywhere.

## What is generated, and from what

| File | Source |
|---|---|
| `manuscript.docx` | built from `manuscript/*.md` |
| `title-page.md` | `authors.yaml` and `paper.yaml` |
| `credit-statement.md` | the `credit` roles in `authors.yaml` |
| `declarations.md` | funding and competing interests, per author |
| `checklist-*.yaml` | the completed reporting checklists |
| `figures/` | the raster and vector exports |
| `MANIFEST.yaml` | every file with its sha256 |

The manifest matters more than it looks. Six months later, "which version did the journal
actually get" has no reliable answer without one.

Two things the generator will tell you rather than paper over. An author with no `credit`
roles produces a statement saying the roles are missing, because most journals now require
them. An author whose `competing_interests` field is empty is listed as having made no
declaration — an empty field is not a declaration of none, and journals ask per author.

## The covering letter

Nothing in the project holds it, and nothing should: it is the one part addressed to a
particular editor about a particular paper at a particular moment.

Write it from the project rather than from memory. Four short paragraphs:

1. **What the paper reports**, in two sentences a non-specialist editor can act on. The
   abstract's Conclusions is the wrong register; say what the reader will learn.
2. **Why this journal.** Not flattery — the actual reason. A recent paper it published that
   this speaks to, or the readership the finding matters for. An editor can tell the
   difference immediately.
3. **What is unusual, if anything.** A preprint, an overlapping submission, a dataset that
   cannot be shared, a conflict that needs declaring. Say it here rather than let it be
   discovered.
4. **The confirmations** the journal asks for: original work, not under consideration
   elsewhere, all authors approved, ethics where applicable.

Do not summarise the abstract. The editor has it.

## Before you send

- Read the pack, not the source. It is a different document once it is assembled.
- Open the .docx and confirm the Zotero citations resolved and the figures are where you
  expect them, at the resolution the journal wants.
- Check the journal profile's `notes` field. That is where the requirements no build can
  check were recorded — suggested reviewers, portal quirks, figure formats — and it exists
  because otherwise you rediscover them at 23:00 on the deadline.
