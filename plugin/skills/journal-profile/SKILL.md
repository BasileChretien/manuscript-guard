---
name: journal-profile
description: Read a journal's instructions for authors and write a machine-checkable profile of its limits, required sections and required statements. Use when a target journal is chosen, when check reports journal-profile-missing or journal-profile-stale, or before submitting to a different journal.
---

# Turning author guidelines into something a build can check

Desk rejection for a formatting breach costs two weeks and is entirely avoidable: too many
words, a missing declaration, an unstructured abstract where a structured one was required.
All of those are mechanical, so they should be caught by a build rather than by an editor.

No journal profile ships with manuscript-guard, on purpose. Author guidelines change
without announcement, so a rule compiled into the tool would eventually be wrong and would
be wrong *silently*. Every profile is read from the journal's own page and stamped with the
date; the gate warns once that date is a year old.

## 1. Read the instructions

Open the journal's instructions-for-authors page with the Chrome tools. Find the section
for the **article type being submitted** — original research, review and short report
usually have different limits, and one profile describes one type.

Read the page. Do not fill the profile in from what you know about the journal, and do not
carry a limit over from a sister journal at the same publisher. If the page does not state
a limit, leave it out: an absent limit is not checked, and a guessed one is worse than
none because it produces confident failures about a rule that does not exist.

## 2. Write the profile

`profiles/journals/<slug>.yaml` in the project — project profiles override anything shipped.

```yaml
schema: manuscript-guard/journal/1
name: "Drug Safety"
publisher: Springer
source_url: https://...        # the page you actually read
retrieved_on: 2026-08-03
article_type: "Original Research Article"
english_variant: en-GB          # only if the journal insists; overrides paper.yaml

limits:                         # omit anything the journal does not state
  abstract_words: 250
  main_text_words: 5000
  references: 100
  figures: 6
  tables: 6

structure:
  required_sections: [Introduction, Methods, Results, Discussion]
  abstract_structured: true
  abstract_headings: [Introduction, Objective, Methods, Results, Conclusions]

required_statements:
  - id: data-availability
    pattern: '(?im)^#+\s*data availability'
    why: "Required in every research article."

references:
  style_name: Vancouver
  numbered: true
  csl: springer-vancouver       # used by offline builds

reporting_guidelines: [STROBE]

notes:
  - "Cover letter must name three suggested reviewers."
  - "Figures at 300 dpi minimum, TIFF or EPS."
```

`notes` is where everything the build cannot check goes — cover letter contents, suggested
reviewers, portal quirks. It is not a dumping ground; it is the list you will otherwise
rediscover at 23:00 on the deadline.

## 3. Point the project at it

```yaml
# paper.yaml
target_journal: drug-safety
```

Then `manuscript-guard check`. Expect failures the first time: that is the profile doing
its job. Word counts are reported alongside the limit, and the counting rule is documented
in `text/sections.py` — citations, tables, images and markup are excluded. Where the
journal counts differently, say so rather than arguing with the tool.

## Changing journals after a rejection

Write the second profile, switch `target_journal`, and run the check. The differences
appear as a list of failures, which is the reformatting job, itemised. Keep the old profile:
you may go back, and the record of what each journal wanted is worth having.
