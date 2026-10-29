---
name: research-communication
description: Fill the slots that communicate build leaves in a post, a press release, a pitch, a newsletter item, a plain-language summary, a video script or a translation, with sentences drawn from the paper's brief alone, never a number or a claim the paper does not make, and run communicate check after. Use when a text under communication holds a write slot, when the author asks for a press release, a thread, a lay summary or a translation of the findings, or when communicate check reports comm-claim-unanchored, comm-fact-not-in-source, comm-claim-stronger, comm-claim-moved, comm-limitation-dropped, comm-primary-missing or comm-number-unbound.
---

# Communicating the paper

A post, a press release or a plain-language summary restates the paper for readers who will
not read it, and each is a place where a number is retyped wrong, a hedge dropped or an
association turned into a cause. `manuscript-guard communicate` holds every such text to
the paper: each sentence that claims is anchored to a statement of the brief, and the brief
to the manuscript. Your part is to write what the tool cannot, in the slots it leaves, from
the brief alone, and to show the author what `communicate check` says of it.

The group is opt-in. If `communicate` refuses with "communication is off", tell the author:
turning it on is their choice, in paper.yaml.

## 1. Start from the brief

The brief is `communication/brief.yaml`: the paper's own sentences, each quoted from the
file it names, under the question, the design, the population, the methods, the primary
outcome, the findings, the limitations and the conclusion. Each statement has an `id`
(`findings.2`), a `text` and its `quote`. Read it before anything else.

- No brief yet: run `manuscript-guard communicate brief`, and ask the author which finding is
  the primary one. They mark it `primary: true`. Never mark it yourself: which result is the
  paper's main one is the author's to say.
- No limitation in it: a press release, a pitch and a plain-language summary must state one,
  and the build will not write them. Ask the author which sentence of the paper states the
  study's limitation, and add it to the brief quoted word for word, with its file. Do not
  write one in your own words.
- A statement's `text` may be shortened by the author; it is held to its quote as any text
  is. Never change a `quote`.

## 2. Write the texts

```bash
manuscript-guard communicate build --channels press-release,plain-language-summary
manuscript-guard communicate status
```

`build` writes each channel's text to `communication/<channel>.md`, and writes only what
`communicate check` passes as written, but for the embargo: while it holds, the text is
written and the check fails it until the embargo lifts. Most texts are the tool's alone: the posts and
threads for Bluesky and Mastodon, the overview slide, the poster outline, the storyboard and
the data announcement. The rest carry slots, `<!-- write: … -->`, each saying what goes there
and from which statements. It will not write over a text that exists, which may hold what
was written into its slots; `--force` writes it again, and only the author decides that.
`status` says which texts are due, given where the paper stands and the triggers in
paper.yaml.

## 3. Fill a slot

Replace the comment with what it asks for, under these rules:

- **Only what the brief says.** Each sentence restates one statement, or several, and adds no
  fact, no number, no citation and no claim the statement does not hold. A reader's question
  the brief cannot answer stays unanswered: say so to the author, do not fill it.
- **Numbers by binding, never typed.** Write `{{results.ror.point}}` as the statement writes
  it, not its value. A number that is not the paper's result has no place.
- **Anchor every sentence that claims.** A sentence with a word of the claim ladder
  ("associated", "increased", "reduced", "caused"), a number or a binding ends with the
  anchor of the statement it restates, `[](#brief:findings.2)`, which prints nothing. A
  sentence that claims nothing needs none.
- **Claim no more strongly.** Keep each hedge ("may", "suggest"), each limit ("in these
  data", "reported") and each negation. Association stays association: never "causes",
  "prevents" or "proves" where the paper says "associated with". A sentence that claims
  less is allowed and is warned.
- **Keep the limitation.** Where the text carries the limitation's statement, keep it, in
  plain words if the slot asks, anchored.
- **Plain words where asked.** A plain-language slot may replace the technical sentence below
  it with plain words, keeping its bindings and its anchor. Explain a term rather than drop
  the hedge that came with it.
- **No person's words but theirs.** A quote from an author, a contact, a signature: leave the
  slot for the author, or write what they dictate.
- **Nothing ahead of the paper.** Before paper.yaml's `publication.status` says the paper is
  online, write no link to its DOI and do not say it is published; say what is true, that it
  is accepted. Before the embargo lifts, nothing is shared.
- **A translation** keeps every binding and anchor of its English source as written, and adds
  no number and no claim. The check holds it to its numbers and anchors only, so read it
  against the source yourself, sentence by sentence.

Delete a slot you have filled. Leave one you cannot fill, and say why.

## 4. Run the check, and show the author

```bash
manuscript-guard communicate check
```

Put right each failure in the text, never by editing the brief to agree with the text:

| It says | What to do |
|---|---|
| a sentence claims and names no statement | anchor it to the statement it restates, or say it without the claim |
| it gives a value, a citation or a number the statement does not | take it out, or anchor to the statement that gives it |
| it claims more than, or otherwise than, its statement | put back the hedge, the limit or the negation; the author alone may allow a stronger sentence in the front matter, with a reason |
| a press release, a summary or a pitch states no limitation | keep the limitation's statement in it |
| a long text states no primary finding, or leads with a secondary one | state the primary finding first |
| a number is typed | write its binding |
| over the channel's length | shorten it, or split a thread at a line of `---` after a blank line |
| it uploads a file the journal's sharing policy does not allow, or one no policy is recorded for | link the DOI and attach nothing; the policy is recorded in the journal's profile (journal-profile) |
| the embargo holds | nothing to do but wait; `communicate status` says until when |

`communication/preview.html` shows every text as it would be read, with what the check
says of each. Show it to the author. Each text is theirs to approve and to share.

## 5. What is never yours to do

- Share, post or send anything. E-mails are drafts only; ResearchGate is added by hand, by
  the author, following `communication/guides/researchgate-steps.md`.
- Mark the primary finding, allow a stronger sentence, or decide that a warning is wrong.
- Upload a version of the paper anywhere the journal's policy does not allow.
- Look up the paper's DOI without being asked: `manuscript-guard lookup --paper` sends it to
  Crossref, and is the author's to run.
