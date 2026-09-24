---
name: word-roundtrip
description: Send a co-author a Word document built from the Markdown source, and bring their edits and comments back without letting a hand-typed number or citation in. Use when a co-author wants a .docx to edit, when an edited .docx comes back, or before running manuscript-guard import.
---

# Bringing a co-author's Word edits back

The .docx is a build artefact: the Markdown is the source, and the document is regenerated
from it. That rule is right, and on its own it is unusable, because co-authors edit in
Word. So the round trip exists, and the whole question is what it may carry back.

It carries prose back and refuses everything that was generated. A naive import would
replace each binding with the number it currently shows, and the manuscript would still pass
every check, because the literals match the analysis today. It would fail quietly months
later, the first time the analysis changed. So a paragraph where a number or a citation
changed is refused, and the co-author's point has to be made at its source, in the analysis
or the ledger.

**The round trip has never been through a real co-author round.** Earlier versions lost text
while reporting success (step 4 lists what is now refused instead). Treat every `--apply` as
something to check, not something that has been checked.

## 1. Before sending

```bash
git commit -am "manuscript as sent to <co-author>"     # know what they received
manuscript-guard build --offline
```

- **Send the `--offline` build, without `--csl`.** The returned document is compared against
  an offline build in the default citation style, so a document built with a journal style
  comes back with every cited paragraph refused. A live Zotero build probably does the same.
- Send `build/manuscript.docx`. `supplementary.docx` cannot be imported.
- Send a document built by manuscript-guard 0.2.12 or later. Earlier builds told Word not
  to record a move as a move, so no paragraph moved in them can be moved back: each is
  refused and has to be moved in the `.md` by hand.
- Do not send `manuscript.annotated.docx` to anyone who will edit it. It carries no source
  stamp and no paragraph identifiers, so nothing in it can come back. It is for someone who
  needs to see where each number came from.
- While the document is out, change nothing it was built from: the manuscript, the
  results, the ledger or `references.bib`. Any change makes `import` refuse the returned
  copy, and forcing it would offer to undo your change. Keep new wording aside and apply it
  after the import.

Tell the co-author, in these words or better ones:

> Edit the wording freely. Please do not change numbers, citations or tables in the text;
> put what you want changed in a comment, because those come from the analysis and the
> reference manager. Please do not split or merge paragraphs. Please keep Track Changes on
> throughout: to move a paragraph, cut the whole paragraph and paste it at the start of
> another one. Reject any change you do not want before sending it back.

## 2. When it comes back

Save it outside `build/`, which every build overwrites. With the plugin installed, a shell
command that copies or moves a `.docx` can be intercepted by the submission guard, so pass
the file's path straight to `import` rather than moving it.

Commit, or at least make sure `git status` is clean. `--apply` writes the source in place and
keeps no backup.

## 3. Read the dry run

```bash
manuscript-guard import returned.docx
```

It changes nothing and reports each paragraph:

| Reported as | Meaning |
|---|---|
| `would merge into manuscript/…` | reworded prose; the bindings and citations in it survive |
| `NOT merged` | refused, with the reason under it: a number or citation changed (`'3.84' comes from results.ror.point`), the paragraph was split or has new text beside it, its identifier came back on text that is not its own (a paste or a copy landed in front of it), a heading was joined into it, text was typed where it renders nothing, the edited text carries markup Word's text cannot bring back (named: a footnote, an HTML comment, a link, an equation, raw TeX…), merged it would not read as the text that came back, the text between two numbers or citations was deleted so they would touch, or it could not be lined up with its source. The whole paragraph is refused, including any rewording in it |
| `came back joined into one` | two or more paragraphs were merged in Word. Not applied; join them in the `.md` yourself |
| `deleted in Word, left in place here` | deleted outright or as a tracked change. Not applied; delete it in the `.md` yourself if that was intended. If it was in fact moved, move it in the `.md`: never retype Word's copy, which has numbers where the source has bindings |
| `moved in Word, left in place here` | cut and pasted where Word recorded no move: Track Changes off, a document built before 0.2.12, or move tracking turned off in Word. Word's copy is shown under it. Not applied; move it in the `.md` and make any rewording there. Never delete it and retype Word's copy |
| `came back in a different place` | a move within one section (between the same two headings, tables or figures), made by cut and paste with Track Changes on, which Word records; `--apply` reorders from the text on disk, so bindings stay intact, and applies any rewording in the same pass |
| `came back in a different place, not applied` | a recorded move in a section that also gained text - a paragraph split, or a new one - or holds a paragraph whose identifier came back on other text, so where its paragraphs now stand cannot be read with certainty. Move them in the `.md` yourself |
| `moved into a different section or file` | a move past a heading, table or figure, into another file, or into the middle of a paragraph (between the halves of a split, or the parts display maths reaches Word in). Not applied; move it in the `.md` yourself |
| `N of M paragraphs … carry no identifier` | headings, table cells, captions and new paragraphs. **None of these was compared** |

Anything refused, joined, deleted, moved without a record Word kept, moved but not
applied, or moved between sections or files makes the command exit 1, with or without
`--apply`; the safe changes are still applied.

A `would merge` line shows the Markdown that will be written, bindings included; a `NOT
merged` line shows what came back from Word. The stamp check refuses a document built from
a different version of the source; see step 6.

For the paragraphs nobody compared, look yourself. Converting both documents to text shows
every difference, compared or not:

```bash
pandoc build/manuscript.docx -t plain -o sent.txt
pandoc returned.docx -t plain -o returned.txt
git diff --no-index sent.txt returned.txt
```

A new paragraph, a changed heading or a table edit is typed into the `.md`, or taken back to
the analysis if it touched a number.

## 4. What `import` refuses on its own, and what still needs you

Each of these once corrupted the source while `import` reported success. They are now
handled, and each has a test:

- A move together with rewording is applied in one pass: the paragraph goes to its new
  place in its section, reworded if it was. A move into another section is reported and not
  applied, rather than pushing a paragraph out of every section in between.
- A paragraph cut and pasted with Track Changes on is moved, not reported deleted. Word
  leaves a paragraph's identifier behind when it cuts the paragraph, and the move is read
  from Word's record of it instead. Two paragraphs moved together are no longer reported as
  a join, and Enter pressed at the start of a paragraph no longer reports that paragraph
  deleted. A move made with Track Changes off is refused and named as a move, never
  reported as a deletion to act on.
- A paragraph split in two in Word is refused, not cut down to its first half, even with a
  moved paragraph pasted between the halves; that move is not applied either.
- Two paragraphs joined in Word are reported as joined and left alone, not duplicated.
  So is a heading joined into the paragraph under it.
- A tab or other Word layout in a paragraph no longer leaks XML into the merge.
- A digit added to a number (`3.84` to `13.84`), or a sign or dash glued in front of it
  (`–3.84`, `<3.84`), is refused as a changed number. A sign separated by a space, or a unit
  added after the number, is not caught: read those in the diff.
- A rewording is refused, not merged, when the edited text carries something Word's text
  cannot bring back: a footnote, an HTML comment, a link, an image, an equation, raw TeX or
  HTML, a superscript or subscript (`10^9^` reads "109" in Word), a hard line break, or
  emphasis or code wrapped around a binding. The reason names it. In a paragraph with a
  binding, markup on one side of the binding does not stop an edit on the other side. A
  paragraph without a binding is all one piece, so one `kg/m^2^` in it refuses every edit to
  it.
- A no-break space comes back as the character it is, so a rewording around it merges and
  keeps it: one in the source ("5 mg", `\ `, `&nbsp;`), and one Word's French AutoCorrect
  put before a colon or inside « ».
- What comes back is written as text, not Markdown: a `*`, an `@name`, a `<` or a `{{` the
  co-author typed is escaped, so it cannot become italics, a citation, a tag or a binding.

What is still yours to do by hand: every refused, joined or deleted paragraph, and every
paragraph without an identifier. Port those edits from the dry run and the text diff above.
`--apply` takes all the safe changes at once; there is no way to pick among them, so if the
dry run shows a merge you do not want, port the whole import by hand instead.

Some things in this version still need care:

- A paragraph moved where Word recorded no move - Track Changes off, a document built
  before 0.2.12, or move tracking turned off in Word - is reported as `moved in Word` and
  left where it was. Move it in the `.md` and port any rewording from the copy shown under
  it. Do not delete it and paste Word's copy in: its numbers and citations would come back
  as typed text, and `check` would then report each one as unbound.
- A reworded paragraph that has a binding or a citation *and* an apostrophe, a quotation
  mark or a `--` in its prose is refused as "could not be lined up with its own source":
  pandoc typesets those characters, so the prose no longer matches. Port that edit by hand.
- A reworded paragraph with a narrative citation (`@key`, no brackets) or a prefixed one
  (`[see @key]`) is refused as "could not be lined up with its own source". Port that edit
  by hand.
- A footnote or an equation edited in Word, a changed link address, or a deleted footnote
  is not seen at all: `import` reads each paragraph's text, and those live elsewhere in the
  file. Look for them in the text diff above.

## 5. Apply, then read what was written

```bash
manuscript-guard import returned.docx --apply
git diff manuscript/
manuscript-guard check
```

Read the whole diff. What to look for:

- Formatting lost. An edited stretch of text comes back as plain text, so bold, italics and
  inline code in it are gone. (A footnote, a comment, a link or an equation is refused
  instead, because merging would delete it.)
- Backslashes. Every character in Word's text that Markdown could read as markup is
  escaped (`CYP2D6\*4`, `\@admin`, `US\$5`), and a `&lt;` of yours may come back as `\<`.
  Each prints as it did. The exception is an escaped straight quote, `\"`, which comes back
  bare and is curled: put the backslash back if the straight quote mattered. A `{` typed
  straight before a binding comes back as `&lbrace;`. Leave it: a bare `{` there joins the
  binding's braces, and `check` reports `{{{results.x}}` as malformed.
- Invisible no-break spaces. An edited stretch brings back the one pandoc puts after an
  abbreviation ("e.g.", "et al.", "p."), and a `\ ` or `&nbsp;` of yours, as the character
  itself. Each prints as it did, but a diff can show a line as changed where nothing
  visible changed.
- Citation text left beside a key, such as `[@smith2020]. 2020).`: a citation ending a
  paragraph, "(Smith et al. 2020).", can be cut at "al.", even when the only change there was
  an invisible one to the kind of space. Restore the paragraph's ending.
- A number or citation the co-author typed. These merge as literals, and `check` then
  reports them as unbound. Bind the number, and turn the citation into `[@citekey]`.
- A binding cut short, a `{{` without its `}}`. `check` now reports it as a malformed
  placeholder; it should not happen, and if it does, it is a bug to report.

After an import the internal review records covering the edited files are stale, and the
built document is out of date. Rebuild before sending anything on.

## 6. Comments, and several co-authors

Comments are printed, never stored. Recording them is the reader's job:

- A co-author's or internal reviewer's comment belongs in an internal review record, so G11
  sees it answered: `manuscript-guard review --record <reviewer> --remit "…" --verdict …`,
  then write each comment into its `findings` with a severity. The
  [review-panel](../review-panel/SKILL.md) skill covers the record.
- A journal reviewer's comment belongs in a revision round. Run
  `manuscript-guard respond --open --from returned.docx` **before** `import --apply`, because
  applying changes the source the comments point at. See
  [reviewer-response](../reviewer-response/SKILL.md).

When several people edited copies of the same build, dry-run every copy before applying any.
Apply one, and port the others by hand. `--force` on the second copy compares it against the
source as it now stands, so it offers to revert everything the first co-author changed.

`--force` is reasonable only when nothing since the build added, removed, reordered or split
a paragraph, or changed what a compared paragraph displays, and even then every hunk has to
be read.

## If you are a model doing this

Never run `--apply` without having read the dry run in full, and never report an import as
done without having read `git diff`. In earlier versions the command's exit code and its
"bindings intact" line were both seen alongside a corrupted source, and the round trip has
still not been through a real co-author round.

When a co-author changed a number, do not type their number into the source to make the
paragraph merge. Ask whether the analysis should change, and if so, change it there.
