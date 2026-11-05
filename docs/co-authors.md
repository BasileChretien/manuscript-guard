# Working with co-authors

A co-author's part has two halves. They read and edit the manuscript in Word, and their
edits and comments come back into the source. And they answer, from a page of their own,
the question no gate can ask: whether a sentence says what its source says. This page has
both. The commands are listed in the [README](../README.md#commands).

## Edits and comments in Word

The .docx is built from the Markdown source, so a co-author edits a copy. Commit the
manuscript as sent, build it (offline, with `--csl`, or live with Zotero fields), and send
`build/manuscript.docx`, and `build/supplementary.docx` if the supplement needs reading too.

```bash
manuscript-guard import edited.docx           # what would change, and the words each edit changed
manuscript-guard import edited.docx --apply   # merge the edits that are safe
```

`import` carries prose back and refuses what was generated: a paragraph where a number or a
citation changed is refused, since a binding replaced by the number it shows would pass
every check until the analysis changed, and the co-author's point is made at its source, in
the analysis or the ledger. A citation a co-author inserted with their own reference manager
is named, with its key where `references.bib` holds it, and not merged as text. A paragraph
moved in Word is moved in the source. A LaTeX manuscript has no round trip yet: `import`
refuses it.

Each Word comment is filed as a finding to answer, in `review/comments/`, and G11 holds it
until it has an answer ([comments a co-author left in Word](review-panel.md#comments-a-co-author-left-in-word)).

A review panel's findings can be answered in Word too. `review --suggestions --round <n>`
writes the edits a round's readings suggest into `build/suggestions/round-<n>.docx`, each as
a tracked change under its reader's name with its finding as a comment. The author accepts or
refuses each change in Word, and `import` of that document merges the accepted words and
writes each answer into the finding's record. The accepting and refusing are the author's.

`approve --as <author>` records an author's approval of the manuscript as it stands, title
page included; `submit` says who has not approved, or who approved a manuscript that has
changed since. It is the author's own act, and the plugin's hook puts it to you before an
agent runs it.

A revision round opened with `respond --open` keeps the document the journal received, and
`build --marked-up`
writes the revision, and its supplement, with every change since that document shown as
Word tracked changes, or highlighted with `--highlight`. `submit` packs it beside the
revision.

How far this has been run: on the one real manuscript so far, two rounds of edits made in
Word 16 as a co-author would make them were imported, by script rather than by a co-author.
The word-roundtrip skill has every case `import` refuses, and why.

## What no gate can check: the checker

Every gate asks whether a number is the number the analysis produced, or whether a quote is
really in the stored source. None can ask what a reader of that source asks: **does the
sentence say what the document says.** A value can be right, its quote can be right, and
the sentence around it can still name the wrong denominator, subgroup or year with every
check passing. On the first manuscript written with this toolkit, that is what happened, and
a co-author reading one item against one quote is what found it.

```bash
manuscript-guard checker build --all                    # one file per author, to send each
manuscript-guard checker import --answers a.json b.json # what they said, into checks/decisions.csv
manuscript-guard checker status                         # outstanding, stale, and who disagrees
manuscript-guard checker recap                          # who checked what, into checks/recap.md
```

`build` writes **one file**. It carries every item, the sentences each value appears in, and the
evidence rendered into the file itself: images as data URIs, tables and excerpts as data. It
opens by double-clicking, in any current browser, offline — nothing installed, no account, no
network,
and nothing sent anywhere by the page. The person presses a button and sends back the answers
file.

What is asked is found from the project's own files: the values quoted from the literature with
the passage each came from, the sentences that cite something, with the passage of the cited
work recorded as supporting each where there is one, each Methods text beside the code of the
steps it points at (and each Methods paragraph pointing at none, as "no code is linked to this
text"), the references, and the authors. A Methods item is answered "Text matches the code",
"Text needs changing", "Code needs changing" or "Not sure".
A number transcribed from a table in a source document is not among them and cannot be — only
the project knows which row it came from — so a project that traces its own numbers adds them in
`checks/items.json`.

A group the project fills, it fills alone: one contributed item in a group means none of the
toolkit's are added to it, since the two are keyed differently and a co-author would otherwise
read the same value twice.

Every answer carries the digest of the item as its maker saw it. If the sentence or the value
moved after they looked, the answer does **not** count as agreement: their yes was about text
nobody has now, and the item is outstanding again. Each page carries the name it was built for
and a token whose digest `checks/bundles.csv` keeps, so a file that names a page and does not
match it is refused; one from no page this project built is recorded as claimed. `checks/decisions.csv` is append-only, because
"was this checked, by whom, and when" is a question asked months later, by whoever is answering a
reviewer.

`recap` writes `checks/recap.md`: each change a co-author asked for, in the manuscript with its
sentence or in the code with its steps, what is still open, the notes on versions of an item
that are gone, and a table of who verified each item. It is tamper-evident by a hash chain,
unsigned: its last section carries the head of a chain over `checks/decisions.csv`, and
`checker recap --check` makes it again and names the first line that differs, so a hand edit
of any line but the one naming the earlier recap (taken as the file gives it, and said to be
unverified), or a row of the record edited, deleted or moved, shows against a copy kept
elsewhere. Someone who can write the record and every copy can still rewrite both. `submit`
packs the tables as `coauthor-verification.md` and warns of each `wrong` or `code` still
open, until any later answer by the person who gave it, or an edit to the item, closes it;
it does not refuse.

What this gives you is a record of who looked, at what exactly, when, and what they said. It is
not a proof that they read it correctly, and nothing here checks their reading.

[Back to the README](../README.md)
