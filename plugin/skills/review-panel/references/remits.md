# Remits worth a reader of their own

Step 1 of the skill lists these. Each section says when the remit is worth a reader, what
that reader is given and asked, and by which route it is read. Each goes into the panel file
like any other remit, with an id, the remit and a `why`.

A remit read by route A only goes in a round that no model reads. `review --run` cannot
leave a reviewer out: it gives every reviewer in the round's panel file to every model, with
the whole manuscript, and without `--round` it runs the first round someone has not reported
in. So record that round's readings before any run, or give every run `--round`. The three
such remits below, the abstract alone, the displays alone and citation support, can share a
round. It is a round like any other: it counts toward
`review.rounds_required`, once complete it supersedes the stale rounds before it, and a later
round without `blinded: true` draws `round-not-blinded`.

## Contradiction

Worth a reviewer of its own on most papers. Where the Methods say something was done and the
Limitations, the Discussion or the registration say otherwise, neither section's reader
notices, because each reads its own part. Either route reads it, but `review --run` does not
send the registration: a model compares the Methods with it only where the manuscript
quotes it.

## The communities the paper draws on

A paper borrows from more fields than its authors work in, and each of them reads it by its
own standards. Before choosing the field readers, list:

- each community whose methods the paper uses: the people who built the estimator, the case
  definition, the scale or the model it applies;
- each community whose data it uses: the people who keep the registry, the claims database
  or the reporting system, and know what its records leave out;
- each community whose results the paper sets its own beside: the trials, cohorts or earlier
  signals it agrees or disagrees with;
- the people who already do what the paper says it does better: the makers and users of the
  method, tool or source it claims to improve on. They are the readers most likely to
  object, and often the reviewers a journal chooses.

For a disproportionality analysis of spontaneous reports, the list might hold
pharmacovigilance for the estimator and the data, hepatology for the case definition of a
liver injury, and the authors of the cohort studies of the drug for the comparison. If the
paper said its method finds a signal sooner than the usual measures, the people who run
those measures would be on it too.

Give each community a reader, with a remit that asks two questions and keeps them apart:

- **Is it right?** Whether the paper uses what it takes from that community as the
  community would: the method where its assumptions hold, the data with their known gaps,
  the comparison of like with like.
- **Is it new?** Whether what the paper presents as its contribution is new to that
  community. A method can be applied correctly and be one the field has used for years; a
  comparison can be new and made wrongly.

The summary of the reading answers each question in a sentence of its own, so that a reading
which answered one and not the other shows it. A remit for the example above might read
"whether the paper uses disproportionality measures and spontaneous reports as
pharmacovigilance would; and, apart from that, whether what it claims as new is new to
pharmacovigilance. Answer each in a sentence of its own in the summary". A model read by
route B is sent only its role and remit, so the remit itself has to ask for the two answers.

The field readers of a default panel are some of these communities already. The list shows
which ones are missing, and the two questions can go into each field reader's remit. One
reader can hold two communities whose standards are the same.

Either route reads this remit. A model answers whether something is new from what it learned
in training, which stops at a date, and route B sends it nothing under `literature/`. Where
the paper's claim to be new or better is what carries it, have a person from that community
read the remit as well, as a reading of its own (`--reading`).

## The abstract alone

Most people who meet a paper read its title and abstract and go no further. One reader
should do the same: they are sent the title and the abstract, nothing else, and asked three
things:

- what they conclude, in a sentence or two, as they would put it to a colleague;
- whether the abstract carries a caveat that would change that conclusion. If it does, they
  quote it; if not, they say what the conclusion would turn on;
- which words they could not have understood from the abstract alone: a term it uses before
  or without defining it, the paper's central quantity first; a term it uses in two senses;
  a method or a comparison named and not said ("the strictest comparison", "adjusted",
  "expected by chance"); a group described by something its definition contradicts. Each is
  a finding quoting the words.

This is not the desk editor's remit, which reads the whole paper and asks whether the
abstract matches it. This reader cannot compare the two, and that is what makes the reading
worth having.

Read it by route A only, since `review --run` sends every manuscript file. Put the title and
abstract in the brief of a fresh agent, or give them to a person who has not read the paper.
Never ask the context that wrote them: it knows what the abstract leaves out. Route A begins
by reading the whole manuscript, which this reader must not do, so if your tool cannot start
a fresh agent and no person is at hand, leave this remit out. Give it an id
such as `abstract-alone` and the remit "what a reader of the title and abstract alone
concludes, whether the abstract carries the caveat that would change that conclusion, and
which of its words such a reader could not understand from the abstract alone".
If the manuscript is in several files and another reader of the same round, such as citation
support, lists them all, keep under `file_sha256` only the file that holds the abstract, as
step 2 of the skill says for a reader of some of them. Alone in its round, this reader keeps
the whole list: a round stays incomplete while a file is on nobody's list.

The reading's summary is that conclusion, and its verdict is on the abstract, not on the
paper. Its findings are about the abstract too: a caveat the
conclusion turns on that the abstract leaves out, places where a reader passes over it, and
words the abstract does not define for a reader who has nothing else.
Keep the reader to that. Given the abstract and a remit about the whole paper, a reader lists
what the paper might lack, and rates it major, without having seen it; those findings are
not this reader's to make.

Once the reading is sealed, set its conclusion beside the Results. Where they support less
than it says, the abstract has to change, even if the reader found no caveat missing: what
this reader concluded is what a reader of the abstract will conclude. No gate makes this
comparison and no record holds it, so give the author the conclusion and the Results it goes
beyond, and let the next round read the abstract they write.

Each fix this reader's findings ask for adds words to an abstract that has a limit, and G4
counts them (`over-journal-limit`). Fit the definitions in by apposition, "the reporting odds
ratio, the odds that a report names the event for this drug against all other drugs", rather
than a sentence of their own, and drop a secondary result before a definition the headline
needs. The manuscript-writing skill's references/clarity.md says more.

## A reader new to the paper

Every reader of a draft except its authors' panel meets it for the first time. A reader of
the field who has not seen the paper stops where a term is used before it is defined, or in
two senses, and readers who have checked its numbers for many rounds no longer see those
places. Worth a reader on every paper, in the round before submission at the latest.

Either route reads it; by route A, have a fresh agent read it, never the context that wrote
the paper. Give it an id such as `newcomer` and the remit "whether a reader of the field who
has not seen this paper can follow it from the title to the conclusion: each term defined
before or where it is first used, the abstract included, for every unit it is used of; one
sense for each term; each group described by what defines it; each claim said to hold 'by
construction' explained; each result the Discussion interprets reported in the Results; and
the order of each sentence's clauses giving the headline its true size". Its findings quote
the first use of each word it could not follow, and say what it took the word to mean.

`check` finds two of these places by their shape: a result the Discussion binds that the
Results do not report (`discussion-not-reported`, a warning) or report only in the supplement
(`discussion-in-supplement`, a note). The rest is this reader's.

## Statistics for a reader without statistical training

A paper's statistics are read by its statistician for whether they are right. They are also
read by people who never studied statistics, and nobody checks that those readers can tell
what a method does or what a number means. Worth a reader on any paper with a test, an
interval, a model or a correction in it.

Either route reads it. Give it an id such as `plain-statistics` and the remit "whether a
reader without statistical training can tell what each method does and what each number
means: a plain one-sentence gloss of each method where it first appears (what an odds ratio
of 1 means and what one below 1 means; what an interval is, and what it is an interval for
where the data are a census; what a correction for several tests does; what 'adjusted for'
and 'conditioning on' mean; what a resampling method does), each range labelled so that it is
not read as an interval, each test the Results use named in the Methods, what 'expected by
chance' stands for, why two intervals that overlap can sit beside a difference whose own
interval excludes no difference, what weight an 'exploratory' or 'post hoc' result carries,
and what each sensitivity analysis is for". The reader is told to answer as someone who
knows the field and not the statistics, and that a gloss the paper gives in the Methods
counts wherever the term comes again.

`check` warns of a method of its list that the Results name and the Methods never do
(`analysis-not-in-methods`); the list holds tests, corrections, intervals and models, and
what it does not hold, and whether a gloss says enough, is this reader's.

## The displays alone

Many readers look at the tables and the figures and read little else, and an editor often
does the same before deciding to read on. Each display has to be read without the text: its
symbols, abbreviations, columns and units defined in its caption, legend or notes; the
comparator it holds the others to named; the test behind each P value said, and whether the
P values are corrected; each line, band and mark said for what it stands; a total that
differs from the count the text gives explained; one sense for each word in it; a legend
that agrees with its caption. Worth a reader on every paper with a display.

Read it by route A only, since `review --run` sends no figure and every manuscript file.
Build the document first (`manuscript-guard build --offline`), and put in the brief of a
fresh agent the rendered figures (the PNG beside each `figures/<name>.svg`, or one you render)
and each table with its caption and notes as the built document prints them, numbers filled
in, and nothing of the text. Give it an id such as `displays-alone` and the remit "for each
table and figure, read alone with its caption, legend and notes: what it shows and what a
reader concludes from it; each symbol, abbreviation, column heading and unit it does not
define; whether it names its comparator and the test behind each P value and their
correction; what each line, band and mark stands for; and each word used in two senses in
it". The reading's summary gives, for each display, what the reader concluded from it.
Under `file_sha256` keep only the files that hold the captions it read, as step 2 of the
skill says for a reader of some of them.

Once the reading is sealed, set each display's conclusion beside the sentence of the text
that cites it. Where the text headlines a comparison the figure does not draw, the strictest
of several comparators in the text and the weakest in the figure say, the figure overstates
the result for every reader who looks at it alone: the figure changes, or the text's headline
does. The figure-review skill's `caption-agrees` check asks the same of each figure when it
is reviewed. `check` warns of one shape of these defects, a caption that points at "the
line" and never says which line (`caption-line-unnamed`), and G14 holds the abbreviations a
display defines for itself to its own uses.

## Interpretation

A sentence of the Results or the Discussion that gives a result binds it, and one that says
what others found cites them, and the gates hold each to its source. The rest is the authors'
reading of their results, "the association probably reflects confounding by indication",
and nothing holds it. `check` counts those sentences, in a note for each file
(`interpretation-sentences`): the sentences of the Results and the Discussion, the
supplement's included, that hold a word of the claim ladder ("associated", "increased",
"caused") and neither a binding nor a citation.
`manuscript-guard explain <file>` prints them after the file's numbers, each with its line.

Worth a reader of its own where the note counts more than a handful. Give it an id such as
`interpretation`, and a remit that holds the list: run `explain` on each file the note names,
and paste what it printed under the heading of sentences, with the file's name above each
part, after the words "whether each of the sentences below follows from the results the
paper reports; for one that does not, say which result it goes beyond or what result it
would need". A model read by route B is sent the manuscript with its numbers filled in and
nothing to say which sentence binds one, so the remit has to carry the list. Either route
reads it; by route A, have a fresh agent read it, not the context that wrote the Discussion.

The reader's findings are about those sentences: a cause claimed from an association, a
mechanism or a subgroup the paper did not study, a comparison with other work that names no
work. Many of the sentences are right, and the reader says so once in the summary rather than
in a finding each. The note itself needs no answer. A finding is answered as any other is: by
rewording the sentence, binding the result it rests on, citing the work it repeats, or an
override that says why it stands.

## Earlier outputs

A paper with earlier outputs on the same data, an abstract or an earlier article, needs an
**earlier outputs** remit: whether each difference from them is a change of method the paper
states and justifies. The related-outputs skill says how it is read.

## Citation support

A paper that rests on its references needs a **citation support** remit. G7 checks that a
quoted number is in its stored source, and the lookup that a cited work exists and was not
retracted. Neither asks whether the work says what the sentence citing it says. A tool cited
to the wrong paper passes all of them: a deep-learning epigenetic clock cited to another clock
paper from the same year, on the same subject, both real.

Read this remit by route A, in the session, and never by route B: `review --run` sends
nothing under `literature/`, by design. If your tool can start a fresh agent, have that one
read it, not the context that drafted the prose, which reads into a source what its own
sentence meant. Give it an id such as `citation-support` and the remit "whether each cited
work says what the sentence citing it says". It runs `manuscript-guard screen` on each stored
source before it reads one, and reports what that quotes: words a page hides from its reader
are no part of what the work says. Hold each sentence that cites a work against that work's
stored source under `literature/sources/`, and report:

- a named tool, method or finding cited to a paper that does not introduce it;
- the wrong population, denominator, subgroup or year;
- a claim stronger than the source: a hedge dropped, an association stated as a cause;
- a review cited for a finding that belongs to a primary study.

Where `literature/passages.yaml` records a passage for a sentence, G7 has checked that its
words are in the source: read the sentence against that passage first, then against the
source around it, since a passage can be the source's words and still not say what the
sentence says. Where a sentence has none, give in the finding the words of the source that
do support it, if any, with where they stand, to be recorded with the literature-verify
skill. Never record a judgement of a passage yourself; that is the author's.

Numbers in the ledger are left to G7, which checks them better. A citation whose work has no
stored source, or one nothing can read, is unchecked, never supported: list those citations
in one `comment` finding, so that a reading with few findings is not taken for one that
checked every citation. The reading does not replace a co-author's check of the same
sentences (the co-author-checking skill). It is filed, sealed and answered like any other.
