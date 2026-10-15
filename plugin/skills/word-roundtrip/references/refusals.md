# What `import` refuses on its own, and what still needs you

Part of the word-roundtrip skill, read when the dry run names a move, a join, a split, a
deletion or anything else `import` will not apply.

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
- A move beside an HTML comment with a blank line in it no longer writes the moved paragraph
  inside the comment. A paragraph with a fence, `</div>`, `\end`, a definition or a
  heading's underline written directly under it is neither moved nor reworded: its edit is
  listed or refused.
- Tables and figures are recognised by what they hold, so deleting a table or pasting in a
  picture no longer hides a paragraph moved past a figure. A heading, table, figure or
  display equation dragged elsewhere, and a table, figure or equation deleted, is reported
  rather than passed over. A deleted heading or caption is listed with the other paragraphs
  without an identifier.
- Two paragraphs joined in Word are reported as joined and left alone, not duplicated.
  So is a heading joined into the paragraph under it.
- A paragraph deleted just before a heading, a table caption or the reference list is
  reported deleted, even when that heading was retitled or that caption edited in the same
  round; it used to be merged as the new title. Not when the new title or caption and the
  deleted paragraph share most of their words: that still merges into the paragraph's slot.
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
- A move or a rewording after which the next build would not find a paragraph again is
  refused: each file is worked out as it would be written and read the way the build reads
  it. A footnote marked because an indented block below would run into it prints as text;
  moved in Word over a plain paragraph, it would become a footnote again and leave the body.
  No move in its section is applied, and the moves are named; rewordings there, and changes
  elsewhere, still land.

What is still yours to do by hand: every refused, joined or deleted paragraph, and every
paragraph without an identifier. Port those edits from the dry run and the text diff above.
`--apply` takes all the safe changes at once; there is no way to pick among them, so if the
dry run shows a merge you do not want, port the whole import by hand instead.

Some things still need care:

- A paragraph moved where Word recorded no move - Track Changes off, a document built
  before Word could record moves, or move tracking turned off in Word - is reported as
  `moved in Word` and left where it was. Move it in the `.md` and port any rewording from
  the copy shown under it. Do not delete it and paste Word's copy in: its numbers and
  citations would come back as typed text, and `check` would then report each one as
  unbound.
- A footnote or an equation edited in Word, a changed link address, or a deleted footnote
  is not seen at all: `import` reads each paragraph's text, and those live elsewhere in the
  file. Look for them in the text diff above.
