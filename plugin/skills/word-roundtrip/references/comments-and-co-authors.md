# Comments, and several co-authors

Part of the word-roundtrip skill, read when a returned document carries comments, when
more than one co-author sends theirs back, or when an import is refused because the
manuscript changed after the build.

## Each comment is filed, and answered

`import --apply` files every comment in the returned document as a finding; the dry run says
where each would go. Each commenter (the comment's author as Word names them) gets one record
per document built: `review/comments/<manuscript|supplementary>-<build>/<commenter>.yaml`.
A finding there holds:
- the comment word for word, its date and the replies to it in Word;
- the words it was made on and the kind of block (paragraph, heading, caption, table, list
  item, quotation, reference list);
- the paragraph's identifier, where the import vouches that it still names the text it was
  built from.

It is filed as `comment`; raise it to `minor` or `major` as you judge.

G11 reports every filed comment that has neither a `resolution` nor an `overridden` reason,
whatever its severity: a warning while you write, a failure in `check --submission`. Answer
each in its record, under the finding:

```yaml
  resolution: Added the 2024 review to the Introduction.
  resolved_on: 2026-10-21
```

or, to leave it as it is:

```yaml
  overridden: The 2019 review is the latest that covers the class.
  overridden_by: <who decided>
```

A reply in Word is kept with its comment, and Word's Resolve is kept as
`resolved_in_word: true`. Neither is an answer, since neither says what was done. G11 also
says when the paragraph a comment was made on has changed since: the change may be the
answer, and it still has to be written down.

Change only `severity` and the answer fields. The record is sealed: a comment reworded or
deleted by hand is reported as `comments-altered`, and `import` adds nothing more to that
record until it is put back. Keep notes in the answer fields, not in `# ...` lines, which
`import` will not write over.

Importing the same document again, or another copy of the same build, files only what is
new. Word keeps an id for each comment through a save, and that is how a comment is known
again; a reply added since joins its comment. A comment is filed even when the edit to its
paragraph is refused. It is filed too when the whole document is refused because the
manuscript changed since the build. It then has an identifier only where its paragraph still
reads as it did, and is marked `unmatched` where it does not: find it by the words it was
made on.

Not filed:
- a review panel's own comments in a document of its suggested edits, and replies to them:
  they are the panel's findings, answered in its records;
- a journal reviewer's comment already seeded into a revision round. Run
  `manuscript-guard respond --open --from returned.docx` **before** `import --apply`,
  because applying changes the source the comments point at; the import then says which
  comments are points of that round. See [reviewer-response](../../reviewer-response/SKILL.md);
- comments in a document whose identifiers do not say whether it is the manuscript or the
  supplement: they are printed, and have to be carried over by hand.

The comments records are internal. Nothing in them goes into a build, a blinded build or the
submission pack, and a commenter's name is a label, not an identity: "Dr. Tanaka" and
"Dr Tanaka" share a record.

## What a build records of each paragraph

A built document records what each of its paragraphs said in the source, what came before
it, and the headings, captions, tables and comments around it. `import` merges an edit only
into a paragraph that still reads that way where it stands.

The build also writes what the document printed, block by block, to a file under
`build/records/`, and the document carries that file's name. `import` reads it to know
what a paragraph deleted or cut in Word had said, and which heading, caption or list item
stood under a paragraph, even after the source changed or the analysis was re-run. The file
stays on the machine that built the document and is never sent. If `import` says the
document `names a record of what it printed ... which is not here`, it is being imported
on another machine or after `build/` was cleaned: nothing wrong is written, but more edits
are refused. Import where the document was built, or carry the refused edits over by hand.
A build that warns `the record of what manuscript.docx printed could not be written` made
such a document: rebuild once `build/` can be written to, and send that one.
Old records are small and safe to delete once every document built from them is back.

Two refusals come from that record. `its identifier came back on text that is either this
paragraph, reworded, or the text that stood above (or under) it` means a paragraph was
rewritten past most of its words in the same round as a block beside it with no identifier
(a caption, a line block, the text after an equation) was deleted or edited, or that the
paragraph was deleted and that block edited: the document is the same either way. `its
identifier came back inside another block, behind '...'` means the paragraph's line was
joined up to the block above it. In both, look at the document: delete the paragraph in
the `.md` if the co-author deleted it, or make the rewording there.

Below a paragraph added or removed since the build, identifiers move by one block and name
their neighbours. A
paragraph there is followed to where it stands now when all of the following read as they
did at the build:
- its text, the block before it and the blocks around it;
- the paragraphs directly before and after it;
- that whole stretch is found once in its file;
- the paragraphs compared keep their order.

A followed paragraph is compared, moved and anchored like any other. Its rewording is still
refused beside a heading or caption missing from the returned document, and when the
paragraph after it as sent did not come back; so is the rewording of the paragraph just
before a followed one that did not come back. Either may be only a deletion.

These are listed as `were not compared`, because the identifier now names other text, and
have to be carried over by hand:
- a paragraph whose own text you changed since the build;
- below a paragraph you added or removed: the one directly below it, and one with a
  heading, caption, table or comment beside it changed too, or the paragraph before or
  after it changed;
- below such a change, one whose text and surroundings are found more than once in its
  file, then or now, and one out of order with the paragraphs compared: of two runs of
  paragraphs you swapped, the middle of one is followed and the rest is not;
- a paragraph you moved into another file;
- in a document built before the record held the blocks around each paragraph, every one
  below a paragraph you added or removed.

A paragraph beside one you reworded, or directly above one you added, keeps its
identifier and is compared as usual. So is the middle of a run of three or more that you
moved together within a file: it stands between the same paragraphs, and is followed.

A paragraph that reads word for word like another in its file, such as "Not applicable."
under two declarations, is also listed once the block before it changed. One of these
deleted or cut with Track Changes off leaves its identifier on the paragraph after it, or
on the line it emptied, and is listed there. Deleted or cut with Track Changes on, or
joined by retyping across the break, it is listed as `did not come back`. A followed
paragraph reported as moved into another section is marked as having the `.md` changed
above it: a heading you moved past it reads the same as a move in Word, so check before
moving it back.

When several people edited copies of the same build, dry-run every copy before applying any.
Apply one, then `--force` the others: each merges only into paragraphs the earlier imports
left alone, and lists the ones they changed as not compared, for you to port by hand. An
edit beside one of those is refused if the two may have been joined in Word. Every hunk
still has to be read: a changed result changes what a paragraph displays without changing
its source, and a paragraph moved past one that was not compared may not be reported as
moved. DESIGN.md's Known gaps lists what the record cannot tell apart.

A document built before paragraphs were recorded in it is refused, `--force` included, and
so is `respond --open --from` on it, when anything it was built from has changed since the
build, the results included. Otherwise it is refused only when a file it carries has front
matter that is now read differently. Rebuild, send the new document, and carry over by hand
anything already written in the old one.

One copy is refused in the same way when the manuscript has changed since its build, as
each of several is: `--force` imports it anyway, an edit merged only where its paragraph
reads as it did at the build, and every hunk still has to be read.
