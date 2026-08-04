---
name: review-panel
description: Assemble a review panel for a manuscript, run the reviews, and record them. Use before submission, when check reports no-review or review-missing, or when a round is complete and a second is due.
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

## 2. Review

Read the whole manuscript once before writing anything. Then, per reviewer, review **only
within that remit** — the value of a panel is that its members are not interchangeable, and
a reviewer who comments on everything is a reviewer who has stopped being a specialist.

Get the digest the record must carry:

```bash
manuscript-guard review --digest
```

If the manuscript is split across several files, record instead which of them this reviewer
read, so a later edit elsewhere does not void their work:

```bash
manuscript-guard review --files
```

Paste the block, then delete the lines for files outside the remit. List honestly: a round
stays incomplete while some manuscript file is on nobody's list, so trimming the map moves
work to another reviewer rather than making it disappear.

Write `review/round-<n>/<reviewer-id>.yaml`. Severity means something:

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

Changing a file a reviewer read marks their review stale — correctly. Once
the round's findings are addressed, re-review against the new text and update the records.

## 4. The second panel is blinded

Set `blinded: true`, and do not read the earlier round's findings before reviewing. A second
panel that reads the first panel's report inherits its sense of what matters, and the errors
worth catching in round two are precisely the ones round one was not looking for. Change the
composition too: a second pass by the same remits mostly confirms itself.

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
not reviewing it. Be harder on text you wrote than on text you did not.
