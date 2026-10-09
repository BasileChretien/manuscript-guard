---
name: co-author-checking
description: Send a co-author the numbers, quotes and references to confirm, and record what they answered. Use when a draft is ready for the question no gate can ask - does the source really say this - or when a co-author has sent back an answers file.
---

# Having a person check what no gate can

Every gate in this toolkit asks whether a number in the manuscript is the number the analysis
produced, or whether a quote is really in the stored source. None of them can ask the question a
reader of that source asks: **does the sentence say what the document says.** A value can be
right, its quote can be right, and the sentence around it can still describe the wrong thing —
the wrong denominator, the wrong subgroup, the wrong year — with every machine check passing.

On the first manuscript written with this toolkit, that is exactly what happened, and what found
it was a co-author reading one item against one quote.

The people who can answer that question are co-authors and colleagues. Most of them will not
clone a repository, install Python, or run a server, and asking them to is how a round of
checking turns into no round of checking.

## What a round is

```bash
manuscript-guard checker build --for "A Co-Author"   # one file, to send to one person
manuscript-guard checker import --answers answers-a-co-author.json
manuscript-guard checker status
```

`build` writes **one file**: a page carrying every item, the sentences each value appears in, and
the evidence rendered into the file itself — images as data URIs, tables and text excerpts as
data. It opens by double-clicking, in any current browser, offline. Nothing is installed, no
account is
made, no network is used, and nothing is sent anywhere by the page. Its own buttons save the
answers file and copy the answers, and the person sends that one file back however they already
send files.

`import` reads an answers file and appends to `checks/decisions.csv`: when, who, which item,
what they said (`ok`, `wrong` or `unsure`), their note, and the digest of the item as they saw
it. The file is append-only, because "was this checked, and by whom, and when" is asked months
later by whoever is answering a reviewer, and a file that gets rewritten cannot answer it.

`status` says how many items nobody has answered, what each person answered, and **where two
people disagree about the same item**, which is a finding in itself.

## Telling the person what to do, in one message

Send the file with three sentences, not a manual. What works:

> Attached is one file. Double-click it — it opens in your browser and needs nothing installed.
> For each item it shows you a sentence from the paper and the passage of the source it came
> from, and asks whether the source says that. Answer the ones you can, press Save, and send
> me the file it saves. "Not sure" is a real answer; use it.

Three things worth saying explicitly, because people assume the opposite:

- **"Not sure" is wanted.** It is the honest answer when a document is ambiguous, and it keeps
  the item outstanding for someone else rather than burying it under a tick.
- **Their note is read.** A "wrong" with no note means someone has to find the problem again
  from nothing, so the page asks for the reason before it moves on from "does not match" or
  "not sure": the note goes on the item it is about.
- **Nothing is being timed.** The page shows an estimate of the work left so the person can see
  the end; it is not a measurement of them.

## Who gets which items

Two people reading the same items is how a disagreement is found, and `status` reports those.
Two people reading different items is how a long list gets finished. Both are worth doing, and
the choice is the author's, not this skill's: **`build` sends every item**, whatever anyone has
already answered, and says how many of them have been answered already; the author decides who
to ask for what. Only an `already` field written into a project's own items file keeps an item
off the page.

What the toolkit finds on its own, with no file written by the project:

| | What the person is asked |
|---|---|
| values quoted from the literature | does the quoted passage say this number |
| sentences that cite something | does the cited source say what this sentence says |
| references | is the record right, and does the work exist |
| authors | is this person's name, degrees, affiliation and role right |

A number transcribed from a table in a source document is **not** among them, and cannot be:
only the project knows that this value came from row 14 of that workbook. A project that traces
its own numbers writes `checks/items.json` against
`contracts/schemas/checking.schema.json`, and those items are asked first, before the four
kinds above. That file is also where a project puts page images, since rendering a page of a PDF
needs a renderer this toolkit does not depend on.

**A group the project fills, it fills alone.** One contributed item in `literature` means the
toolkit offers none of its own in that group, and `build` says how many it left out. Otherwise
the same value arrives twice under two identifiers — they are keyed on different things, so
nothing can tell they are the same — and the person reads it twice. To take the toolkit's items
for a group instead, leave that group out of the project's file.

## When an answer is refused

An answer carries the digest of the item as its maker saw it. If the sentence or the value moved
after they looked, the digest no longer matches and **the answer is not recorded as agreement**:
their yes is about text nobody has now. The item goes back to outstanding and the refusal says
which item and which person.

That is not a malfunction to work around. Rebuild the file and ask again for those items, and
say why — a co-author who is asked twice about the same sentence and told nothing will assume
their first answer was lost.

## What to do with the answers

A `wrong` is a finding, and it is handled like any other: fix the manuscript, or the ledger, or
both, and re-run `manuscript-guard check`. Where the problem is in a value's provenance rather
than in the prose, the [literature-verify](../literature-verify/SKILL.md) skill covers the
ledger, and [results-binding](../results-binding/SKILL.md) covers a number that should be bound
differently. Where a whole round of checking is being recorded for a journal, the
[submission-pack](../submission-pack/SKILL.md) skill covers what goes with the submission.

**Do not resolve a `wrong` by changing the item and re-importing the same answers file.** The
digest exists to stop exactly that.

## What this does not claim

The record is a person's word, written down accurately. It is not a proof that the source says
what they said it says, and nothing here checks their reading. What it gives you is: who looked,
at what exactly, when, and what they said — and an answer that cannot quietly survive the text
it was about being edited afterwards.

A file is also not a guarantee that anyone opened it. `status` says who has answered; it cannot
say who meant to.
