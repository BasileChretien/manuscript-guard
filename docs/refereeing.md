# For editors and reviewers

A journal sends its editors and referees manuscripts in confidence. `manuscript-guard audit`
reads one on your own computer and sends nothing of it anywhere: the checks run here, with no
model. This page is about reading a paper someone else wrote. For your own, see
[Auditing a paper you already wrote](audit.md).

## Keep it away from a model

Journals and publishers forbid putting a submitted manuscript into an AI tool that does not
keep it confidential. The audit's report quotes the manuscript's lines, so the same holds for
the report: do not paste it into a chat with a model, and do not let a coding agent run the
audit or read its output. Run it yourself, in a terminal no agent can read. When `--journal`,
`--authors`, `--design` or `--cited` is given, the audit says so on stderr, and the plugin's
hook asks you before an agent runs it. The paper-audit skill tells an agent to stop on a paper you were sent to review
or to handle, and to give you the commands instead. `compare`, which sets a revision beside
the version before it, says the same every time it runs, and the hook asks about it too.

What leaves the machine: nothing, unless you ask. `--lookup` asks Crossref, OpenAlex,
DataCite, doi.org and PubMed about each DOI and PMID of the reference list, and with
`--cited` asks Europe PMC for each cited work's abstract by its PMID or DOI; it sends those
identifiers and nothing else, never a sentence, a title or a name. `--lookup --dry-run` lists
what it would send. The set of DOIs a paper cites is a weak fingerprint of it, and a contact
address you set in the environment for the registries names you to them.

## A referee

```bash
manuscript-guard audit paper.docx --lookup
```

The audit described in [Auditing a paper you already wrote](audit.md), without outputs to
compare with: each P against the statistic beside it, each estimate against its interval, a
table's totals and its n (%), the means of whole numbers, a flow printed as a list, the
Abstract against the Results, a count held back that a total gives away, the words (G6, G14)
and the reference list, and with `--lookup` each work the registries say was retracted,
withdrawn or put under concern. It reads a .docx, Markdown, LaTeX and a PDF.

**A PDF.** Most referees are sent a PDF, and the audit reads its text:

```bash
manuscript-guard audit paper.pdf --design observational --cited cited.md
```

It needs `pdftotext` (poppler's, or Xpdf's), which [Installing](install.md) lists; without it
the PDF is refused with a sentence, and nothing is audited. The page's running head and foot,
its number and the line numbers a manuscript prints in its margin are taken out, and every
place is a page and a line: "page 3, line 12", the line counted down that page's text as
read, and "(numbered 145)" where the PDF numbers the line itself. What runs on the text runs
on a PDF: each P against its statistic, each estimate against its interval, the numbers
against the outputs `--against` names, the Abstract against the Results, the reference list
and `--lookup`, the causal words, the cited sentences, and the words (G6, G14). What does not:

- **Tables.** A PDF's table is lines of text, not rows of cells: its numbers are read as the
  text's, and no total, share, mean or count held back is checked in it.
- **Headings.** A PDF marks none. A line is read as a heading only where it holds a section's
  name and nothing else, numbered or not ("Methods", "2. Results", "REFERENCES"). A section
  under any other title is read as part of the one before. Where one name stands alone on two
  lines, a structured abstract's own headings perhaps, which is the paper's is not read: the
  lines are placed in no section, the Abstract is not compared with the Results, and the
  report says why.
- **Layout.** A number split by a hyphen at a line's end, or set across two columns, may be
  read as two; a running head the reading did not recognise is read as text. The two
  `pdftotext` builds read some PDFs differently, and the report names the one that read it.

A PDF in a folder given to the audit is not read, since one there is as often a figure or a
copy of the source: name it on its own.

**Causal words.** An observational study shows an association, and a sentence that says one
thing causes another claims more than its design can show. You declare the design; the tool
does not guess it:

```bash
manuscript-guard audit paper.docx --design observational
```

Each sentence of the Abstract (every heading under it, and an abstract in a Markdown
file's front matter), the Discussion and the Conclusion is read for a word that
claims a cause: cause, causes, caused, causing, causal, causally, "demonstrated that",
"proved that" and their other tenses. A sentence that holds a hedge ("may", "might",
"appears") or a negation ("not", "cannot", "no") is passed over, and so is one that carries a
citation (a number in brackets, a LaTeX `\cite`, an author and a year in brackets), since the
cause may be a cited trial's. The rest are warnings, `causal-word-observational`, which
`--strict` does not count. The Methods and the Results are not read: "a causal diagram" there
describes the analysis. Only those words are read: "reduced the risk" claims an effect, and
is not.

**Cited sentences.** Whether a cited work says what the sentence says it does is your
reading, and the tool lays it out for you:

```bash
manuscript-guard audit paper.docx --cited cited.md --lookup
```

`cited.md` (or `cited.html`) has a row for each work each citation names: the sentence, its
file, line and section, the citation as typed, and the reference list's entry as typed with
its DOI and PMID; with `--lookup`, the title, the year and the standing the registries give
(retracted, withdrawn, under concern), and the abstract Europe PMC holds; and an empty last
column, "Does it support the sentence? (yours)". A citation typed right after a sentence's
stop, "X. [3]" or "X.[3]", is that sentence's. The file quotes the manuscript, so keep it as you keep the
manuscript; the audit's own output gives only the counts. It does not write over a file that
is already there, which may hold your judgements. It reads a number in brackets where the
reference list is numbered, and a LaTeX `\cite`; it does not read a citation by author and
year, a superscript number in a .docx, or Word's Zotero and EndNote fields, and the file says
so. An abstract is kept only in the folder `--lookup-cache` names.

## An editor

```bash
manuscript-guard audit paper.docx supplement.docx --journal journal.yaml
manuscript-guard audit paper.docx --journal journal.yaml --authors authors.yaml --strict
```

**`--journal`** names the journal's profile, which the editor keeps: a profile of the kind an
author keeps in a project, filled from the journal's own instructions
([Journal profiles](journal-profiles.md)). To start one, make a folder for it with
`manuscript-guard init journal-desk`, and inside it `manuscript-guard journal --template
my-journal` copies the annotated template to `profiles/journals/my-journal.yaml`. The first paper named is the main document; the
rest are read as the rest of the submission and not held to the journal's limits, since a
journal counts the main document's words and display items. The report gains a section,
"Journal (G4)", that holds the main document to:

- the word limits of its abstract and main text, and its limits on figures and tables;
- the abstract found under its heading, and the headings of a structured abstract;
- the sections and the statements the profile requires (funding, competing interests,
  ethics, data availability, a trial's registration: whatever the profile lists);
- the data availability statement's phrasing and identifier, where the profile records the
  journal's data policy; a dataset's DOI is held to the paper's own reference list, and where
  no list was read (a LaTeX paper's list is in its `.bib`) that is said instead;
- the boxes the journal prints beside the abstract (highlights, key points).

The tables are those the paper types: in Markdown and in a .docx each table pandoc reads, in
a block quotation as well, and in LaTeX each captioned table float. A table written in HTML,
or indented in a list item, is not counted, and the report then says the table limits were
not checked rather than that the paper is within them. The data statement's DOIs are held
to the main document's own reference list, not a supplement's.

And it says what it did not check, since those read an author's project rather than the
manuscript: the profile's quotes against the journal's stored page, the citation style, the
figure files' artwork, a LaTeX class's rules, and the graphical abstract, which a submission
sends as a file of its own. The profile's rules no gate checks (`manual:`) are printed as a
checklist for the editor to tick, each with its quote. The profile's English is the one G14
holds the paper's spelling to, unless `--english` says otherwise. An invalid profile is
refused with the schema's errors, and nothing is audited.

**The Document section.** With `--journal`, each .docx is read for what it holds besides its
text, from its XML as Word writes it: the tracked insertions, deletions and moves that hold
text, the comments, the runs of text formatted as hidden, and each person's name Word keeps,
with the field it is in (the document's author and last editor, the author of each tracked
change and comment, and the people who edited it). None of it is counted by `--strict`: some
journals ask for a revision with its changes tracked. A PDF holds none of these as Word keeps
them: the Author of its Info dictionary is read, through `pdfinfo` where it is installed (the
report says so where it is not), and nothing else it keeps, its other fields, its XMP
metadata and its annotations among them. A PDF's tables and figures are not counted, so the
journal's limits on them are listed as not checked.

**`--authors`**, where the profile says the journal's review is double- or triple-blind, names
the authors to look for, in authors.yaml's shape:

```yaml
authors:
  - given: Ada
    family: Example
    orcid: 0000-0002-1825-0097
    email: ada@example.org
affiliations:
  - text: Department of Examples, University of Nowhere, Somewhere
```

Each author's name, ORCID iD and e-mail address, and each part of an affiliation of three
words or more, is looked for in each document given, the supplement as well as the main
document, where the build looks for them in a blind submission: in a .docx its text, notes,
comments, tracked deletions, author fields, links' addresses and pictures' text; in Markdown
its text; in LaTeX each file of its tree and the PDF and SVG pictures it places; in a PDF its
text and the Author of its Info dictionary. The reference
list is left out where the audit finds it, since a blind journal asks its authors to cite
their own work in the third person. Each one found is listed with its place and counted by
`--strict`. Where the review is not blind, nobody is looked for, and the report says so. A
referee never passes `--authors`.

**Self-citation.** With `--authors` and `--lookup`, each author is looked for in the author
lists the registries keep for each reference, by family name (folded as the reference check
folds one: accents, case, particles) and first initial; and with `--lookup` the journal's own
papers among the references are counted, by the profile's `name` against each record's
journal, folded. The report gives the counts and the entries, never a ratio or a verdict, and
a namesake counts as much as the author. Without `--lookup` nothing is counted: the reference
text is not read for names.

## A revision

```bash
manuscript-guard compare paper-v1.docx paper-v2.docx --response letter.docx --comments mine.md
```

`compare` sets the revised manuscript beside the version you read the first time. Both are
read as `audit` reads a paper (a .docx, Markdown, a `.tex` with the files it inputs, or a
PDF), and each line of the report is a fact with its place, never a verdict:

- **Sections**, matched by their titles as printed, without their numbers: the same, changed
  (with the words in each version), new, gone, or moved out of the order they stood in.
- **Tables**, matched by their label ("Table 2"; "Supplementary Table 1" and "Table S1" are one
  table), and one with no label by its caption; then cell by cell, each column by its header
  and each row by its first cell, with the columns and rows added and removed. A table
  renumbered reads as one gone and one new.
- **Figures**, by their label: their captions the same or changed. A picture is not compared.
- **Numbers, citations and bindings** of the prose, gone, new or changed, each at its line in
  the new version. The reference list's and the tables' numbers are left to those.
- **Claims**: each changed sentence that now claims more, less or the opposite, as `reworded`
  reads one ("may" gone, "associated" made "increased", a "not" gone or new).
- **v2 audited**: the audit above, run on both versions, each finding of the new one marked
  "stood in v1" where the first version's audit gave the same finding, word for word, and
  "new in v2" otherwise.

Where either version is a PDF, its places are pages and lines, as in the audit, and its
tables and figures are not compared: the report says so once for each, and never says a table
is the same. A table or a figure the letter or your comments name is "not compared" there.

**`--response LETTER`** reads the authors' letter (.docx, Markdown or text). Each quotation of
four words or more, and each block quotation, is looked for in both versions, as whole words
and numbers ("was 2.1" is not found in "was 2.15"):

| The quotation is | The report says |
|---|---|
| in v2 and not in v1 | new as quoted (a note) |
| in both | quoted as revised, but v1 had it (a warning) |
| in v1 only | it quotes the first version (a note) |
| in neither | it quotes text neither version holds (a warning) |

Straight quotation marks are paired within a paragraph; where a paragraph's are odd in
number, or one follows a number (an inch's mark, 5", or a quotation that ends in a number),
none of its straight quotations is read, and the report names the paragraph. Curly marks
are read whatever they hold. A letter that quotes your own comments block by block gets
the last line for each of them,
unless `--comments` is given and holds the words, when it says so instead. Each "Table N",
"Figure N" and "Supplementary Table N" the letter names, and each title of a section as the
paper prints it (in the case it is printed), is a line: where the letter names it, and whether
it changed between the versions. Whether the change is the one the letter claims is yours to
read.

**`--comments MINE`** reads your own comments on the first version: numbered entries ("1.",
"2)", "Comment 3:") where two or more lines open with a number, a paragraph each otherwise; in
a .docx, each paragraph is one, since Word writes a list's numbers into no text.
A comment is matched to the revision only by a passage it quotes, in double quotation marks or
as a block quotation, or by a table, a figure or a section it names. A quoted passage is
unchanged in v2, changed (with the sentence the new version has where it stood), gone, or not
in v1 either. A comment with neither is listed as not matched, to read. Nothing in the report
says a comment was answered: a changed sentence may be the change you asked for, or another.

The report goes to the screen, or with `--out FILE` to a file that is not there yet (it writes
over nothing); `--json` gives it in the audit's shape, each finding with its section and its
mark. It exits 0 once the comparison ran, whatever it found, and 2 where a file could not be
read. Nothing is sent: the comparison has no `--lookup`. It prints the confidentiality notice
every time, and the plugin's hook asks you before an agent runs it, since its report quotes
both versions.

## What `--strict` counts

What [Auditing a paper you already wrote](audit.md) lists, and an author named in a document
the journal reviews blind. Not the journal's limits or missing statements, which a journal
may count otherwise than this tool does, nor what the Document section counts, nor the causal
words, the cited sentences or the self-citation counts. `compare` has no `--strict`: none of
what it reports is counted.

## What is not checked

The reporting checklist (CONSORT, STROBE and the rest) needs the authors' completed checklist,
and the model checks need the analysis's model cards: neither is in a submitted manuscript,
and the report does not pretend otherwise. The limits of each check are in
[DESIGN.md](../DESIGN.md), under "Known gaps".
