---
name: reporting-checklist
description: Retrieve a reporting guideline's official checklist (STROBE, CONSORT, PRISMA, RECORD, SPIRIT, TRIPOD, ARRIVE and others) and record it so the build can check that every item is addressed. Use when check reports checklist-not-retrieved, or when adopting a new guideline.
---

# Retrieving a reporting checklist

**No checklist text ships with manuscript-guard, and none should be written from memory.**
Item text that is approximately right produces confident coverage of the wrong things, which
is worse than having no checklist at all, and it would be an odd thing to put inside a
toolkit whose whole argument is that approximately right is not good enough.

What ships is a *recipe* for each guideline: where its items sit in the guideline's own
document. The document is downloaded on request, the recipe reads the items out of it, and
every item is checked to appear verbatim in it. The profile is then a function of the
published checklist, and it can be checked against the original the same way a literature
quote can be checked against its source.

## 1. Get the official document

Recipes ship for STROBE, RECORD, RECORD-PE, CONSORT, SPIRIT-2025, PRISMA-2020,
PRISMA-2020-abstracts, READUS-PV, READUS-PV-abstracts, TRIPOD-development,
TRIPOD-validation, TRIPOD-development-validation and ARRIVE-2.0. Name the guideline in
`paper.yaml` as the recipe is named (`reporting_guideline: [STROBE]`, a list). Extensions
hold only their own items. RECORD adds to STROBE, so a study that follows RECORD lists both,
and RECORD-PE adds to RECORD, so one that follows it lists STROBE, RECORD and RECORD-PE.

```bash
manuscript-guard fetch STROBE
```

That downloads the guideline's own document into `profiles/reporting/sources/` in the
project, prints the licence before it starts, and checks the file against the checksum the
recipe records. It is a download, so tell the author which guideline and which site before
you run it. READUS-PV is licensed for non-commercial use only, and the command says so.

- If the recipe records no download address, `fetch` says so. Open the guideline's page,
  save the file into `profiles/reporting/sources/` yourself, or pass
  `--url <direct link> --save-url` to record the address for next time.
- If the checksum does not match, the published checklist may have been revised, and the
  recipe's column layout may no longer fit it. Read what changed before going on.
- If the checklist is only available as a scanned table or an image, say so and ask the user
  for a copy they can read. Do not reconstruct it.

## 2. Transcribe the items

```bash
manuscript-guard transcribe STROBE
```

That builds `profiles/reporting/STROBE.yaml` from the stored document. It keeps the
guideline's own item numbering, including sub-letters like `6a`, because that is what
journals and reviewers refer to, and it fails if an item cannot be found verbatim in the
document. Name the guideline: with no name the command tries every recipe. The profile
records how thoroughly it was verified, which differs. A Word table lets every item's full
text be checked, and a PDF laid out in columns only each item's opening clause.

**Do not write or edit the profile by hand.** It is generated, the write guard refuses edits
to `profiles/reporting/*.yaml` where the hooks run, and a hand-edited profile is no longer a
function of the published checklist. If an item is wrong, the recipe is. A recipe in the
project at `profiles/reporting/recipes/STROBE.recipe.yaml` takes precedence over the shipped
one and is the one file in that directory you may edit. Then run `transcribe` again.
`--allow-changed` transcribes a document whose checksum no longer matches the recipe. Use it
only after reading what changed.

**A guideline with no recipe.** Write one at `profiles/reporting/recipes/<NAME>.recipe.yaml`,
starting from the shipped recipe whose document looks most like yours:

```bash
python -c "from manuscript_guard.paths import SHIPPED_RECIPES; print(SHIPPED_RECIPES)"
```

That needs the Python that has manuscript-guard installed. Under pipx, run
`pip show -f manuscript-guard` through `pipx runpip manuscript-guard`, and it lists the same
files.

A recipe names the document and says which table and columns hold each item's number, topic
and text. Its `meta` block needs `name`, `source_url`, `retrieved_on` and `licence`, and
should carry the address and checksum of the copy it was written against. Save the document
into `profiles/reporting/sources/` and run `transcribe <NAME>`. A recipe that does not fit
the document fails, where a wrong one would have produced a plausible wrong transcription.

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
