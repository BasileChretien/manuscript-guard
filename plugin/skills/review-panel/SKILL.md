---
name: review-panel
description: Assemble a review panel for a manuscript, have it read by an agent, by people or by models from several providers, and record the readings. Use before submission, when check reports no-review, review-missing or reading-missing, or when a round is complete and a second is due.
---

# Reviewing a manuscript before a journal does

Every other gate checks a property of the text. This one exists because somebody competent
has to disagree with the paper, and be recorded doing so.

The record is the contract. A model can produce one in minutes; a co-author can write one
by hand; the gate treats them identically. What it enforces is that the panel was written
down, that each member reported, that the reports apply to the manuscript as it now stands,
and that every major finding was answered. **It cannot tell you a review was any good.** A
reviewer who writes "looks fine" satisfies the gate and helps nobody, so the work below is
the part that matters.

## 1. Build the panel for this paper

A panel's composition decides what it can see. Three methodologists will not notice that
the clinical framing is wrong, and a panel with no reader in it will approve a paper nobody
can follow. Derive the panel from what the paper actually is:

- Read `paper.yaml` — the design, the reporting guideline, the target journal.
- Read the journal profile, if there is one. A clinical journal and a methods journal reject
  for different reasons.
- Ask what would have to be wrong for the paper's central claim to fail, and put someone on
  the panel whose job is to notice each of those things.

A working default for an observational pharmacoepidemiology paper: a
**pharmacoepidemiologist** (design, definitions, confounding), a **biostatistician**
(estimator, intervals, reproducibility from what is reported), a **clinical specialist** in
the therapeutic area, a **reporting-guideline auditor**, an **adversarial reviewer** whose
remit is to find the reason to reject, and a **desk editor** judging triage. Take from that
what the paper needs and add what it needs that is not there.

Write it to `review/panel-<n>.yaml`, including *why* each reviewer is on it. Two reviewers
with the same remit are one reviewer.

If there is no panel file when `manuscript-guard review --run` is used (route B below), it
writes a starter panel that assumes no field: design, statistics, reporting and an
adversarial reviewer in round one; a desk editor and a specialist reader in round two. That
is a place to start. A panel fitted to the paper sees more, so edit the file.

## 2. Review

There are two ways to get a remit read, and one round can use both.

### Route A: read it yourself

Read the whole manuscript once before writing anything. Then, per reviewer, review **only
within that remit** — the value of a panel is that its members are not interchangeable, and
a reviewer who comments on everything is a reviewer who has stopped being a specialist.

When a reviewer has finished reading, have the toolkit start their record, so that nobody
types a digest:

```bash
manuscript-guard review --record <reviewer-id> --round <n> \
    --remit "<what they are responsible for noticing>" \
    --verdict <pass|minor-revision|major-revision|reject> --summary "<their overall comment>"
```

That writes `review/round-<n>/<reviewer-id>.yaml` with the digest of the manuscript and of
each of its files filled in. It adds the reviewer to `review/panel-<n>.yaml`, and creates the
panel if there is none, so put the panel's `rationale` and each reviewer's `why` there
(step 1). The verdict is required, because a record with a placeholder verdict is a claim
that somebody looked. `--by` names who did the reading and defaults to the reviewer id. The
command refuses to overwrite a record, so a second reading of a changed manuscript is a
further round (step 3).

Then add the findings to the file. If the manuscript is split across several files and this
reviewer read only some of them, delete the other files' lines under `file_sha256`, so that a
later edit elsewhere does not void their work. `manuscript-guard review --files` prints those
lines, and `--digest` prints the digest of the whole manuscript, if you want to compare.
List honestly: a round stays incomplete while some manuscript file is on nobody's list, so
trimming the map moves work to another reviewer rather than making it disappear.

When a remit is read by more than one reader, a co-author and a model for instance, each
reading is a record of its own. Add `--reading "<who>"` and the record is written beside the
reviewer's plain one, as `<reviewer-id>.<who>.yaml`, and neither replaces the other. The
command also lists that reader under the reviewer's `readers` in the panel file, and the
round then needs a reading from every reader listed there (`reading-missing` until it has
one). Only the readers the panel lists are read: a file copied beside a record by hand is
reported as `reading-unnamed` and counts for nothing until its reader is added to the panel.

### Route B: have models from several providers read it

A panel read by one model shares that model's blind spots. List the models once in
`paper.yaml`, each as `provider/model`, with model names taken from each provider's own
list:

```yaml
review:
  models: [openai/<model>, mistral/<model>, moonshot/<model>]
```

```bash
manuscript-guard review --providers       # the providers, each key's variable, set or not
manuscript-guard review --run --dry-run   # what would be sent where; sends nothing
manuscript-guard review --run             # the same statement, then asks, then sends
```

Each provider's API key is read from its environment variable (`--providers` names them)
and is never written anywhere. A provider that is not built in is added under
`review.providers` with its `base_url`. A model run on the same machine through Ollama
needs no key and sends nothing anywhere.

**The manuscript is unpublished, and sending it to a provider is the author's decision,
not yours.** If you are an agent, run the dry run, show the author its statement of which
files go to which host, and send only when they have said yes in so many words. Do not add
`--yes` on your own judgement. What a provider keeps or does with what it is sent is in its
terms, not in this toolkit.

By default every model reads every reviewer's remit; `--one-each` deals one model to each
reviewer in turn, for fewer calls. The statement before the run gives the number of calls.
Each reply is checked against a fixed shape and refused if it does not fit. A reply cut
short, a refusal, or text that is not the review is never repaired or filed: it is kept
under `review/round-<n>/refused/` to read, and counts for nothing. The panel file names
every reader that was asked, so if one provider fails the round shows as incomplete
(`reading-missing`), and running the command again asks only for what is missing. If a
reader is not going to report, take it out of that reviewer's `readers` in the panel file.

What each model is sent is the paper's title, keywords, journal and guideline, the journal
profile and reporting checklist where the project has them, every manuscript file with its
numbers and tables as a reader sees them, and that reviewer's role and remit. Figures are
not sent, so a model's reading says nothing about them. The authors, the results files and
the earlier rounds are not sent either.

A model's record is filed with its findings numbered and none answered. Do not answer them
for the author, and do not edit what the model said: the record is what that reader found.

## Severity means something

- **major** — blocks a submission build until answered. The paper's claim does not follow,
  a method is wrong or unreported, a number cannot be reconstructed.
- **minor** — should be fixed, does not invalidate anything.
- **comment** — including things done *well*, which are worth recording so a later revision
  does not remove them.

Write findings a person could act on. "The Methods are unclear" is not a finding. "No case
definition is given; in real reporting data the choice between a narrow preferred-term list
and an SMQ changes the numerator substantially" is.

## 3. Answer every major finding

A major finding needs a `resolution` saying what was done, or an `overridden` saying why it
was not. **An override is a legitimate answer to a reviewer; silence is not.** Recording the
reason is what makes it a decision rather than an oversight, and it is the thing you will
want when a real reviewer asks the same question.

With several readers, every major finding from any of them has to be answered, in the
record that raised it. One reader's clean reading does not answer another's finding, and
nothing merges two findings that say the same thing: answer each, and say in the second
that it is the first one again. `manuscript-guard review` lists who read each remit, what
each concluded and the round's strictest verdict. The verdict is reported and decides
nothing; the findings are what block.

Changing a file a reviewer read marks their review stale — correctly. Once the round's
findings are addressed, read the revised text as a further round (`manuscript-guard review
--record <reviewer> --round <n> --verdict <verdict>`, or `review --run --round <n>` with a
panel written for it) rather than editing the old records: a
record's digest is the only thing that says which version was read. When that round is complete, it
supersedes the stale rounds before it, which stay as the history of the review. Their
unanswered major findings still have to be answered.

## 4. The second panel is blinded

Set `blinded: true`, and do not read the earlier round's findings before reviewing. A second
panel that reads the first panel's report inherits its sense of what matters, and the errors
worth catching in round two are precisely the ones round one was not looking for. Change the
composition too: a second pass by the same remits mostly confirms itself.

A round read through route B is blinded by construction: each request is built from the
list above, and the earlier rounds are not on it.

Two rounds by default; `review.rounds_required` in `paper.yaml` changes it.

## 5. Check

```bash
manuscript-guard review                # where things stand
manuscript-guard check --submission    # submission standards: open findings fail
```

Ordinary builds warn, so you can keep producing a document to read. The version you send
anywhere has to have its major findings answered.

## If you are a model doing this

The failure mode is agreeableness. A panel of six personas that all approve the manuscript
has told you nothing and cost you an afternoon, and it is the likely outcome unless each
reviewer is given something specific to attack. Before writing a record, ask what would
have to be true for this reviewer to reject the paper, and check whether it is.

Reviewing your own draft is worth less than reviewing someone else's, and worth more than
not reviewing it. Be harder on text you wrote than on text you did not. If the author has
models from other providers configured, their readings are the fresh ones: yours counts
beside them, not instead of them.
