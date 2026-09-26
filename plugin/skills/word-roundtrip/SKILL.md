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
> reference manager. Please do not split or merge paragraphs. Tracked changes are fine, but
> reject any you do not want before sending it back.

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
| `NOT merged` | refused, with the reason under it: a number or citation changed (`'3.84' comes from results.ror.point`), the paragraph was split or has new text beside it, a heading was joined into it, text was typed where it renders nothing, the edited text carries markup Word's text cannot bring back (named: a footnote, an HTML comment, a link, an equation, raw TeX…), merged it would not read as the text that came back, the text between two numbers or citations was deleted so they would touch, everything but a table, figure or misspelt placeholder was deleted so it would build with no identifier, or its numbers, citations and markup could not be told apart from its prose, as when two tokens touch in the source. The whole paragraph is refused, including any rewording in it |
| `came back joined into one` | two or more paragraphs were merged in Word. Not applied; join them in the `.md` yourself |
| `deleted in Word, left in place here` | deleted outright or as a tracked change. Not applied; delete it in the `.md` yourself if that was intended |
| `came back in a different place` | a move within one section (between the same two headings, tables, figures, lists, quotations or other blocks without an identifier); `--apply` reorders from the text on disk, so bindings stay intact, and applies any rewording in the same pass |
| `moved into a different section or file` | a move past a heading, table, figure, list, quotation or other block without an identifier, or into another file. Not applied; move it in the `.md` yourself |
| `paragraph(s) without an identifier … came back different` | a heading, list item, quotation, caption or new paragraph was edited (`-` the old text, `+` the new), deleted or added. Not applied; make the edit in the `.md`. A paragraph moved past one of these may not be reported as moved, so compare the documents as text (below) |
| `… came back in a different order` | headings, list items or quotations came back unchanged but reordered (`~`). Not applied; reorder them in the `.md` |
| `N of M paragraphs … carry no identifier` | headings, table cells, captions, list items, block quotes and new paragraphs. **None of these was compared**; those outside tables that changed are listed by the two rows above, and an edit inside a table is not reported at all |

Anything refused, joined, deleted or moved between sections or files, and any paragraph
without an identifier that came back different or in a different order, makes the command
exit 1, with or without `--apply`; the safe changes are still applied.

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

A new paragraph, a changed heading, a list or quotation edit, or a table edit is typed into
the `.md`, or taken back to the analysis if it touched a number.

## 4. What `import` refuses on its own, and what still needs you

Each of these once corrupted the source while `import` reported success. They are now
handled, and each has a test:

- A move together with rewording is applied in one pass: the paragraph goes to its new
  place in its section, reworded if it was. A move into another section is reported and not
  applied, rather than pushing a paragraph out of every section in between.
- A paragraph split in two in Word is refused, not cut down to its first half.
- Two paragraphs joined in Word are reported as joined and left alone, not duplicated.
  So is a heading joined into the paragraph under it.
- A tab or other Word layout in a paragraph no longer leaks XML into the merge.
- A digit added to a number (`3.84` to `13.84`), or a sign or dash glued in front of it
  (`–3.84`, `<3.84`), is refused as a changed number. A sign separated by a space, or a unit
  added after the number, is not caught: read those in the diff.
- A citation ending a paragraph, "(Smith et al. 2020).", is no longer cut at "al."; a
  narrative `@key` comes back as `@key`, not as the text "Smith (2020)"; and apostrophes
  and dashes no longer stop a paragraph with a binding from taking a rewording.
- A rewording is refused, not merged, when the edited text carries something Word's text
  cannot bring back: a footnote, an HTML comment, a link, an image, an equation, raw TeX or
  HTML, a superscript or subscript (`10^9^` reads "109" in Word), a hard line break,
  emphasis or code wrapped around a binding, or code holding a `--`, a `...` or a quote
  (written back as text, `--offline` printed as "–offline"). The reason names it. In a
  paragraph with a binding, markup of those kinds on one side of the binding does not stop
  an edit on the other side. Markup the import does not recognise does: `[Methods]`, a link
  to the heading, refuses every edit to its paragraph. A paragraph without a binding is all
  one piece, so one `kg/m^2^` in it refuses every edit to it.
- A no-break space comes back as the character it is, so a rewording around it merges and
  keeps it: one in the source ("5 mg", `\ `, `&nbsp;`), and one Word's French AutoCorrect
  put before a colon or inside « ».
- An edit that would make pandoc read a citation differently is refused: a space deleted
  after a full stop before a citation, or between two citations, or text deleted between a
  citation and a number.
- What comes back is written as text, not Markdown: a `*`, an `@name`, a `<` or a `{{` the
  co-author typed is escaped, so it cannot become italics, a citation, a tag or a binding.

What is still yours to do by hand: every refused, joined or deleted paragraph, and every
paragraph without an identifier. Port those edits from the dry run and the text diff above.
`--apply` takes all the safe changes at once; there is no way to pick among them, so if the
dry run shows a merge you do not want, port the whole import by hand instead.

One thing still needs care:

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
  Each prints as it did. The exception is a straight quote: an escaped one of yours, `\"`,
  comes back bare, and one the co-author typed is left bare, and pandoc curls both. Put a
  backslash in front where the straight quote mattered. A co-author who only turned curly
  quotes straight has changed nothing that reaches the build. A `{` typed straight before a
  binding comes back as `&lbrace;`. Leave it: a bare `{` there joins the binding's braces,
  and `check` reports `{{{results.x}}` as malformed. Once a `<` before a letter (`<LLOQ`,
  `<µg`) stands earlier in the paragraph, a `>` in an edited stretch comes back as `\>`, or
  as `&gt;` where it ends a value after an `=` (`=>`, `HR=2.1>1`). If that `<` is yours or
  a value's rather than the co-author's, a straight quote typed just after an `=` comes
  back as `\'` or `\"`, and prints straight; so does a curly `’` typed there to close a
  quote of yours. Leave them: pandoc can read a bare
  `<` and `>` with words between them as an HTML tag and drop everything from one to the
  other, and `check` reads `ROR \> 2` as the threshold it prints. A `<` before a number or
  a space, as in `p < 0.05`, opens nothing, and what follows it comes back as typed.
- Invisible no-break spaces. A `\ ` or `&nbsp;` of yours in an edited stretch comes back as
  the character itself. It prints as it did, but a diff can show a line as changed where
  nothing visible changed. The one pandoc puts after "e.g." or "et al." is written back as a
  plain space, because pandoc puts it back at the next build.
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
