---
name: journal-profile
description: Choose a target journal with the author, then read that journal's instructions for authors and fill the annotated profile template with its limits, required sections and required statements. Use when choosing where to submit, when check reports journal-profile-missing or journal-profile-stale, or before submitting to a different journal.
---

# Turning author guidelines into something a build can check

Desk rejection for a formatting breach costs two weeks and is entirely avoidable: too many
words, a missing declaration, an unstructured abstract where a structured one was required.
All of those are mechanical, so they should be caught by a build rather than by an editor.

No journal profile ships with manuscript-guard, on purpose. Author guidelines change
without announcement, so a rule compiled into the tool would eventually be wrong and would
be wrong *silently*. Every profile is read from the journal's own page and stamped with the
date; the gate warns once that date is a year old.

## 1. Choose the journal with the author, not for them

Do this before reading any guidelines, and do it as a conversation. Propose a shortlist —
typically three to five — and for each one give the author what they actually need to
decide:

- **Why this journal for this paper.** Scope and readership, in a sentence that refers to
  the manuscript in front of you rather than to the journal's own blurb.
- **What it will cost.** Article-processing charge, and whether it is waived or discounted
  for **this paper's authors**. This decides more submissions than anyone admits.
- **What it will take.** Rough time to first decision, and the format the reformatting job
  implies — a structured abstract, a hard word limit, a required checklist.
- **The honest risk.** Where you think it is a reach, say so.

**Read the affiliations out of `authors.yaml` before saying anything about cost.** Every
project has different ones, and a transformative agreement or waiver belongs to an
institution, a country, or a funder — never to a journal in the abstract. Check the ones
this paper actually lists, and say which author's affiliation the waiver would run through,
since it is usually the corresponding or submitting author's that counts. Where an
institution's agreements are not published, say you could not confirm it rather than
implying a price either way; getting this wrong costs real money.

The same applies to waivers for authors in low- and middle-income countries, which several
publishers offer automatically and many authors do not know about.

Rank them and say which you would send first and why. Then let the author choose: they know
things you do not — a reviewer conflict, a grant reporting requirement, a co-author's
history with an editor. Record the shortlist and the decision in the project, because the
second choice matters again after a rejection.

Search the journal's current pages rather than relying on memory. Scope statements, charges
and turnaround times all move, and a recommendation built on a stale impression wastes the
author's time in a way that is invisible until it has.

## 2. Read the instructions

Open the chosen journal's instructions-for-authors page. Find the section for the **article
type being submitted** — original research, review and short report usually have different
limits, and one profile describes one type.

Read the page. Do not fill the profile in from what you know about the journal, and do not
carry a limit over from a sister journal at the same publisher. If the page does not state
a limit, leave it out: an absent limit is not checked, and a guessed one is worse than
none because it produces confident failures about a rule that does not exist.

Note what the page does *not* say, too. A journal that is silent on data availability is
not a journal that forbids the statement, and the difference belongs in `notes`.

## 3. Fill the template

```bash
manuscript-guard journal --template drug-safety
```

That copies an annotated template to `profiles/journals/drug-safety.yaml`. Every field
carries a comment saying what it means, where on a typical guidelines page to find it, and
what to do when the page is silent — the answer to the last being always to delete the line.
Fill it in against the page, delete what the journal does not state, and delete the comments
you no longer need.

Project profiles override anything shipped, so this is also how you correct a profile that
has gone stale.

The shape it ends up as:

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

## 4. Point the project at it

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
