---
name: review-panel
description: Assemble a review panel for a manuscript, have it read by an agent, by people or by models from several providers, and record the readings. Use before submission, when check reports no-review, review-missing, reading-missing, reading-altered or reading-unsealed, or when a round is complete and a second is due. Not for answering a journal's reviewers (use reviewer-response), nor for a co-author's check of the sources (use co-author-checking).
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

One remit is worth a reviewer of its own on most papers: **contradiction**. Where the Methods
say something was done and the Limitations, the Discussion or the registration say otherwise,
neither section's reader notices, because each reads its own part.

A paper with earlier outputs on the same data, an abstract or an earlier article, needs an
**earlier outputs** remit: whether each difference from them is a change of method the paper
states and justifies. The related-outputs skill says how it is read.

A paper that rests on its references needs a second: **citation support**. G7 checks that a
quoted number is in its stored source, and the lookup that a cited work exists and was not
retracted. Neither asks whether the work says what the sentence citing it says. A tool cited
to the wrong paper passes all of them: a deep-learning epigenetic clock cited to another clock
paper from the same year, on the same subject, both real.

Read this remit by route A, in the session, and never by route B: `review --run` sends
nothing under `literature/`, by design. If your tool can start a fresh agent, have that one
read it, not the context that drafted the prose, which reads into a source what its own
sentence meant. Give it an id such as `citation-support` and the remit "whether each cited
work says what the sentence citing it says". Hold each sentence that cites a work against
that work's stored source under `literature/sources/`, and report:

- a named tool, method or finding cited to a paper that does not introduce it;
- the wrong population, denominator, subgroup or year;
- a claim stronger than the source: a hedge dropped, an association stated as a cause;
- a review cited for a finding that belongs to a primary study.

Where `literature/passages.yaml` records a passage for a sentence, G7 has checked that its
words are in the source: read the sentence against that passage first, then against the
source around it, since a passage can be the source's words and still not say what the
sentence says. Where a sentence has none, give in the finding the words of the source that
do support it, if any, with where they stand, to be recorded with the literature-verify
skill. Never record a judgement of a passage yourself; that is the author's.

Numbers in the ledger are left to G7, which checks them better. A citation whose work has no
stored source, or one nothing can read, is unchecked, never supported: list those citations
in one `comment` finding, so that a reading with few findings is not taken for one that
checked every citation. The reading does not replace a co-author's check of the same
sentences (the co-author-checking skill). It is filed, sealed and answered like any other.

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

Then add the findings to the file, and seal it once they are all there:

```bash
manuscript-guard review --seal <reviewer-id> --round <n>   # --reading "<who>" for a named reading
```

The seal is a digest of what the reader wrote: the verdict, the summary, the rejection tests
and each finding. Answering a finding later is not covered by it; changing what the reader
wrote is, and `check` reports that as `reading-altered`. Seal what the reader wrote, not a
version you have tidied. A reading is sealed once.

Where the fix for a finding is a matter of wording, the finding can carry the wording, before
the seal:

```yaml
- id: r2-03
  severity: minor
  finding: The aim is stated as a gap rather than a question.
  edits:
    - old: has not been examined
      new: remains unexamined
```

`old` is the manuscript's words exactly as the `.md` has them, enough of them to appear only
once in the manuscript's prose. An edit is words only: no number, binding, citation, table or
figure changes, no markup, nothing across two paragraphs, and at most ten in a reading. The
author sees each one as a Word tracked change under the reader's name (step 3), so write
only the edits the reader would sign. One that cannot be placed exactly is not written, and
the finding still stands.

If the manuscript is split across several files and this
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
`review.providers` with its `base_url`. A model that Ollama runs on the same machine
needs no key and sends nothing anywhere. An Ollama cloud model (a name ending in `-cloud`
or `:cloud`) is not one: Ollama's server passes it on to Ollama's own servers, though the
address is `localhost`. The statement before a run says so for those names; it cannot see
any other server on this machine that forwards what it receives.

**The manuscript is unpublished, and sending it to a provider is the author's decision,
not yours.** If you are an agent, run the dry run, show the author its statement of which
files go to which host, and send only when they have said yes in so many words. Do not add
`--yes` on your own judgement. What a provider keeps or does with what it is sent is in its
terms, not in this toolkit.

Where `paper.yaml` says `custodian: {restricts_sending: true}`, a run sends to no provider
the data custodian has not authorised, and says so; only a model the built-in Ollama runs on
this machine needs no authorisation. The authorisation
is the custodian's own act: they run `manuscript-guard sign --as "<them>" --finding
G11/custodian/send-to/<provider>`, after reading the dry run's requests. Never run it for
them, and never take the restriction out of `paper.yaml` to get a run through.

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
not sent, so a model's reading says nothing about them: G11 warns (`figures-not-seen`) when a
model passes a remit that covers figures. The authors, the results files, the stored
sources under `literature/` and the earlier rounds are not sent either, so citation support
is not a remit for a model read this way (step 1).

The models of one provider share their blind spots. G11 warns (`round-one-provider`) when
every reading of a round came from one provider; a model of another provider, or a person,
is the answer.

A model's record is filed with its findings numbered and none answered, and sealed. Do not
answer them for the author, and do not edit what the model said: the record is what that
reader found, and an edit to it is `reading-altered`.

## Severity means something

- **major** — blocks a submission build until answered. The paper's claim does not follow,
  a method is wrong or unreported, a number cannot be reconstructed.
- **minor** — should be fixed, does not invalidate anything.
- **comment** — including things done *well*, which are worth recording so a later revision
  does not remove them.

A finding may say what it asks of the authors (`ask`): a **disclosure** of what they have, a
**computation** of a new number, or **new data**. A computation is a new emitted result and a
new reconciliation of the Methods with the code, so a reader asking for one says why the
numbers and tables already reported cannot answer it.

Write findings a person could act on. "The Methods are unclear" is not a finding. "No case
definition is given; in real reporting data the choice between a narrow preferred-term list
and an SMQ changes the numerator substantially" is.

## 3. Answer every major finding

A major finding needs a `resolution` saying what was done, or an `overridden` saying why it
was not. **An override is a legitimate answer to a reviewer; silence is not.** Recording the
reason is what makes it a decision rather than an oversight, and it is the thing you will
want when a real reviewer asks the same question. Put the name of the person who decided in
`overridden_by`: the submission pack's manifest lists every override with it. An agent
drafts the reason; the author decides, and the name is the author's.

Findings that carry edits can be answered in Word. `manuscript-guard review --suggestions
--round <n>` writes `build/suggestions/round-<n>.docx`, with each edit the round's readings
suggest as a tracked change under its reader's name and its finding as a comment, and lists
each edit it could not place and why. The author opens it, accepts or rejects each change,
and replies to a finding's comment to say why one was refused; then `manuscript-guard import
build/suggestions/round-<n>.docx --apply` merges the accepted words, refuses the document
while any of the panel's changes is undecided, and writes each answer into its record: an
accepted edit as the finding's `resolution`, a refused one with a reply as its `overridden`,
the reply's author as `overridden_by`. A refused edit with no reply leaves the finding open.
The accepting and refusing are the author's; an agent does not do them in the document.

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

## A design round, before the analysis

The panel above reads the manuscript, once there are results. A design round reads the
plan, `design/plan.md`, and the feasibility results, while the analysis can still change.
Give it one or two reviewers whose remits ask whether the design supports the inference the
plan intends, naming the risks of the study type: confounding, selection, immortal time,
missing data, multiplicity, leakage. Where `paper.yaml` declares the `study_type`, each
reviewer is also sent what a plan for that design has to settle, with its sources; declare
it before the round. The models in `review.models` can read it, as they
read the manuscript: `manuscript-guard review --design --run --dry-run` shows what would be
sent (the plan and the feasibility results, never the manuscript), and the author runs
`review --design --run` and answers yes. Never add `--yes` for them. Or file each reading by
hand:

```bash
manuscript-guard review --record methodologist --design --round 1 --verdict major-revision \
  --remit "Whether the design supports the inference the plan intends"
manuscript-guard review --seal methodologist --design --round 1   # once the findings are in
```

A remit read by more than one reader, a person and a model or two models, takes a reading
from each: `--reading <reader>` on both commands files it as
`review/design/round-1/methodologist.<reader>.yaml` and lists the reader in the panel. Each
reading's majors are answered on their own.

```bash
manuscript-guard review --record methodologist --design --round 1 --reading "Dr Tanaka" \
  --verdict minor-revision
```

G12 says a major finding not answered (a warning until submission), and a reading of a plan
that has changed since. Answer a finding with what the plan now does, in `resolution:`. An
objection left standing, `overridden:` with a reason, is the statistician's to accept: they
sign it with `manuscript-guard sign`, as the warning's hint says. Never run `sign` for them.

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
