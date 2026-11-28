# After a pass that was meant to change only the wording

Part of the manuscript-writing skill, read after a language edit and when
`manuscript-guard reworded` reports.

A language edit, yours or anybody's, is trusted with the words and with nothing else, and
`check` cannot see whether it kept to them: one confidence bound written where the other
stood is still a binding that resolves. Prove it, before the edit is committed:

```bash
manuscript-guard reworded       # the manuscript against the last commit
```

It holds every binding, every citation key and every typed number to its place. The
comparison is with the last commit, so what the author changed and has not committed is in
it too: before a language pass on a text with such changes, ask for them to be committed,
and the report is then of the pass alone.

- A failure is one of them gone, new or changed. Put it back as it stood. If the change is
  meant, it is a change to the paper: say so to the author in those words, and do not call
  the edit a rewording.
- A warning is the same ones in another order. A clause that moved does that, and so do
  two values that changed places. Read the sentence the warning names and make sure of
  which.
- A warning that a number "may have lost a minus sign", or gained one, is a dash before
  it that came or went where it could be a sign or the dash of a range: after emphasis, a
  raised figure, a product sign, the "e" of an exponent. A range retyped is nothing; a
  sign lost is a number changed. Read the place.
- A warning that the dash before a number "stands at another of its" places is the
  same figures with a dash at a different one of them: two clauses that changed places,
  or a minus sign that went from one number to the other. Read both places.
- A number is compared as typed, so "3" spelt out as "three" fails. Leave the figures of a
  manuscript as the author typed them unless you were asked to change them.
- A warning that a sentence "claims more" or "claims less" than it did, or "may now say
  the opposite", is a word that sets how strongly it claims that came or went in a
  sentence the edit changed: a hedge ("may", "appears"), a limit ("only", "in this
  sample"), a negation ("not", "no") or a word of the ladder from "consistent with"
  through "associated", "predicts", "contributes to" and "increased" to "caused". A
  language pass keeps what a sentence claims: put the words back, unless the author, the
  evidence or a reviewer asked for the move, and then say so to the author.

For a text that is not in git, keep a copy before the edit and name it:
`manuscript-guard reworded manuscript/main.md --before copy-of-main.md`.
