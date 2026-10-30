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
or to handle, and to give you the commands instead.

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
withdrawn or put under concern. It reads a .docx, Markdown and LaTeX; a referee who has only
the PDF can ask the editor for the source.

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
journals ask for a revision with its changes tracked.

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
its text; in LaTeX each file of its tree and the PDF and SVG pictures it places. The reference
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

## What `--strict` counts

What [Auditing a paper you already wrote](audit.md) lists, and an author named in a document
the journal reviews blind. Not the journal's limits or missing statements, which a journal
may count otherwise than this tool does, nor what the Document section counts, nor the causal
words, the cited sentences or the self-citation counts.

## What is not checked

The reporting checklist (CONSORT, STROBE and the rest) needs the authors' completed checklist,
and the model checks need the analysis's model cards: neither is in a submitted manuscript,
and the report does not pretend otherwise. The limits of each check are in
[DESIGN.md](../DESIGN.md), under "Known gaps".
