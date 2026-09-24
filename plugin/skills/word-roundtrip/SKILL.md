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

**The round trip has never been through a real co-author round, and running it has shown it
can lose text** (step 4). Treat every `--apply` as something to check, not something that
has been checked.

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
| `NOT merged` | a number or citation in the paragraph changed. The whole paragraph is refused, including any rewording in it |
| `deleted in Word, left in place here` | not applied; delete it in the `.md` yourself if that was intended |
| `came back in a different place` | a move within one file; `--apply` reorders from the text on disk, so bindings stay intact |
| `moved into a different file` | not applied; move it in the `.md` yourself |
| `N of M paragraphs … carry no identifier` | headings, table cells, captions, list items, block quotes and new paragraphs. **None of these was compared** |

The preview shows the Word text, not the Markdown that will be written. The stamp check
refuses a document built from a different version of the source; see step 6.

For the paragraphs nobody compared, look yourself. Converting both documents to text shows
every difference, compared or not:

```bash
pandoc build/manuscript.docx -t plain -o sent.txt
pandoc returned.docx -t plain -o returned.txt
git diff --no-index sent.txt returned.txt
```

A new paragraph, a changed heading, a list or quotation edit, or a table edit is typed into
the `.md`, or taken back to the analysis if it touched a number.

## 4. Do not apply when the dry run shows any of these

Each has been seen to corrupt the source while `import` reported success:

- **A move together with any rewording.** The rewordings are written at positions measured
  before the reorder, so text lands inside the wrong paragraph and a binding can be cut in
  half. `check` may not notice. Port the edits by hand instead.
- **A paragraph split in two in Word.** The first half keeps the identity, and the source
  paragraph is cut down to it.
- **Two paragraphs joined in Word.** The text is duplicated.
- **Anything that looks like XML in a preview line** (`</w:r>`, `<w:t`): a tab in Word
  leaks raw markup into the merge.

There is no way to apply some hunks and not others, so in these cases port the edits by hand
from the dry run and the text diff above.

## 5. Apply, then read what was written

```bash
manuscript-guard import returned.docx --apply
git diff manuscript/
manuscript-guard check
```

Read the whole diff. What to look for:

- A binding cut short: a `{{` without its `}}`.
- Formatting lost. An edited stretch of text comes back as plain text, so bold and italics in
  it are gone. A paragraph with no bindings or citations is replaced whole, and loses its
  footnotes and link targets too.
- A number or citation the co-author typed. These merge as literals, and `check` then
  reports them as unbound. Bind the number, and turn the citation into `[@citekey]`.
- A changed number that got through as a digit next to a binding: `1{{results.ror.point}}`.

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
done without having read `git diff`. The command's exit code and its "bindings intact" line
have both been seen alongside a corrupted source.

When a co-author changed a number, do not type their number into the source to make the
paragraph merge. Ask whether the analysis should change, and if so, change it there.
