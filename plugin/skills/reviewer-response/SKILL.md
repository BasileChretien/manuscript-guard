---
name: reviewer-response
description: Answer a journal's reviewers point by point, with every claimed revision checked against the manuscript as it was sent. Use when a decision letter with reviewer comments arrives, before revising anything, when check reports point-unanswered, response-claims-nothing, claimed-change-did-not-happen, claimed-change-missed-the-point or anchor-unrecorded, or before resubmitting.
---

# Answering the reviewers

A response to reviewers is made almost entirely of claims about the paper: "we have revised
the Methods", "the analysis has been rerun", "Table 2 now reports the counts". The journal
cannot see the diff, and the authors write the letter from memory at the end of a long
revision. The commonest failure is not dishonesty. It is a response written before the
change, and the change then made differently, or not at all.

G13 checks the letter against the manuscript. For that it needs to know what the manuscript
looked like when it went to the journal, which is why step 1 comes first.

## 1. Open the round before changing anything

```bash
manuscript-guard respond --open
```

This writes `revision/round-<N>.yaml`, recording a digest of every manuscript file as it
stands now. That record is the baseline every claimed revision is checked against. Open
the round after revising and the baseline is the revised text, so nothing you changed can
be confirmed.

If revising has already started, the baseline has to come from the version that was sent.
Check out the submitted commit somewhere (a `git worktree` works) and run
`manuscript-guard review --files` there. It prints one digest per manuscript file. Paste
the entries under `submitted_files:`, without the `file_sha256:` line above them, which the
schema would refuse. Tell the author that is what you did.

`received_on` is set to the day the round was opened. Correct it to the date of the
decision letter.

When the comments are in a Word document this toolkit built, seed the round from it:

```bash
manuscript-guard respond --open --from reviewed.docx
```

Each comment becomes a point, grouped by comment author. A comment attached to a paragraph
records which one in `where`, and the round keeps a per-paragraph baseline so that point can
be checked more tightly (step 4). The command refuses a document built from an older version
of the source. `--force` overrides that, and a comment then keeps its paragraph only where
that paragraph still reads in the source as it did at the build; the others are recorded
without `where`, the command says how many, and each such point needs its paragraph named in
its own words. A document built before paragraphs were recorded is refused even with
`--force` when anything it was built from has changed since: rebuild and have the comments
made on the new document. A document the toolkit did not build, which includes anything the
journal produced, cannot seed a round even with `--force`.

Seeded point ids follow the alphabetical order of the reviewers' names, not the journal's
numbering. Renumber them to match the decision letter.

## 2. Enter the points

Most reviews arrive as text in a decision letter or a PDF. Replace the placeholder reviewer
in the round file by hand:

```yaml
reviewers:
  - id: reviewer-1              # lower case, digits and hyphens
    points:
      - id: "1.1"               # the journal's numbering, QUOTED
        comment: >-
          The reviewer's words, copied, not paraphrased.
  - id: editor
    points:
      - id: E1
        comment: ...
```

Three traps, each silent until it is expensive:

- **Quote numeric ids.** `id: 1.2` is a number, the round fails the schema, and a round that
  fails the schema has none of its points checked and fails `check` at every stage.
- **Delete the placeholder text.** "Quote the reviewer here, in their words." is not flagged
  by anything and is printed in the letter.
- **Keep the file name** `revision/round-<N>.yaml`. A `.yml` file is ignored without a word.

## 3. Answer each point

Every point needs a `response`, and then either what changed or why nothing did:

```yaml
      - id: "1.1"
        comment: The case definition is not stated.
        response: We have added the case definition to the Methods.
        changed:
          - kind: manuscript
            name: main.md                 # relative to manuscript/
            note: case definition, Methods, second paragraph
      - id: "1.2"
        comment: Please report the counts behind the odds ratio.
        response: The two-by-two table is now reported.
        changed:
          - kind: results
            name: two_by_two              # the emitted key, without "results."
      - id: "1.3"
        comment: A Bayesian shrinkage estimate should be used.
        response: We considered this and have kept the frequentist estimate.
        rebutted: >-
          With a single drug-event pair there is no multiple-comparison problem for
          shrinkage to address; the Discussion now says so.
```

What each kind of `changed` entry actually proves:

| `kind` | `name` | Checked |
|---|---|---|
| `manuscript` | `main.md`, `supplementary/S1.md` | the file differs from the baseline, by any byte; for a point seeded with `--from`, the paragraph it is attached to must differ too |
| `results` | `case.n_cases`, `two_by_two` | the key is emitted, not that its value changed |
| `figure` | `forest.svg` | the file exists in `figures/`, not that it changed |
| `analysis` | `01_model.py` | the file exists in `analysis/`, not that it changed |

So for three of the four kinds the check is weaker than the letter sounds. Make sure the
change really happened, and say what it was in `note`, which is the one field written for
the editor.

A rebuttal is a complete answer. Disagreeing with a reviewer is often right, and a reason in
`rebutted` is what separates a decision from an oversight. It is printed after the fixed
words "We have not made this change:", so do not repeat that phrase in `response`.

"Done." with nothing under it is `response-claims-nothing`, because it names nothing that
could be checked.

## 4. Revise, then check

```bash
manuscript-guard respond                 # writes the letter, lists anything unverified
manuscript-guard respond --submission    # the same findings, as failures
```

| Code | Means |
|---|---|
| `point-unanswered` | the response is blank; a `rebutted` alone does not count |
| `response-claims-nothing` | a response with neither `changed` nor `rebutted` |
| `claimed-change-did-not-happen` | the named file is byte-identical to the baseline, or the key or path does not exist |
| `claimed-change-missed-the-point` | the paragraph the reviewer commented on is unchanged, though the response says the manuscript was revised. It is found by its text, so moving it or adding paragraphs above it does not count as revising it |
| `anchor-unrecorded` | the point names a paragraph (`where`) the round's baseline does not hold, which only a round written by hand or by an older version has. Check the paragraph yourself, then delete `where` |

All five warn during the revision and fail at submission. `respond` ignores `stage:` in
`paper.yaml`, so pass `--submission` yourself. For `claimed-change-missed-the-point`, if
revising somewhere else in the file really was the right answer, say so in `rebutted`.

The paragraph a point is attached to is found by its text, not by where it sits. Adding,
removing or moving paragraphs around it, a heading written above it, a div put round it or
a comment on a line of its own above or below it does not change the answer: it counts as
revised once its source text differs, which a re-wrapped line with the same words, or a
comment opened above it and closed below, also does. The `where` in the
round file still names a position, though, so after restructuring a section it may point a
person reading the file at another paragraph. And a word-for-word copy of the paragraph left
elsewhere keeps it reading as unrevised.

The letter is `build/response-to-reviewers.md`, regenerated every time and covering every
round. Do not edit it; the wording lives in the round file, and the plugin refuses writes to
`build/`. The `Changed:` lines print internal names such as `main.md`, so a good `note`
matters. There is no Word version of the letter. Paste it into the journal's form or the
author's letter template.

## 5. The rest of the resubmission

- **The internal review panel goes stale.** Revising changes files the panel read, and
  `review-stale` fails at submission. Each reviewer whose files changed has to read them
  again and have the record updated, as the
  [review-panel](../review-panel/SKILL.md) skill describes. Recording a new panel round does
  not clear the staleness of an earlier one. Plan for this before promising a date.
- **Under the plugin**, any shell command containing `--submission` is intercepted, the whole
  submission check runs, and the command is refused if anything fails. `respond --submission`
  can therefore be refused because of another gate. The refusal shows the first eight
  failures; `manuscript-guard check --stage submission` lists them all without being
  intercepted.
- `manuscript-guard submit` puts the letter in the pack.
- A second round: `respond --open` again, before touching anything. Earlier rounds stay
  checked against the current manuscript, so a round-1 claim can start failing later.

## If you are a model doing this

Write each response after making the change, not before. A letter drafted in advance is
exactly the failure this gate exists for, and it only checks that something changed, not
that it answers the point.

Do not name a file in `changed` because it changed for some other reason. The byte check
will pass and the letter will be false, and only you can tell the difference.

Do not agree with every reviewer. Agreeing to an analysis the authors cannot justify changes
the paper for the worse. Draft the rebuttal and let the author decide.
