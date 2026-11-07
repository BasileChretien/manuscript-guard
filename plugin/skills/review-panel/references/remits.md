# Remits worth a reader of their own

Step 1 of the skill lists these. Each section says when the remit is worth a reader, what
that reader is given and asked, and by which route it is read. Each goes into the panel file
like any other remit, with an id, the remit and a `why`.

A remit read by route A only goes in a round that no model reads. `review --run` cannot
leave a reviewer out: it gives every reviewer in the round's panel file to every model, with
the whole manuscript, and without `--round` it runs the first round someone has not reported
in. So record that round's readings before any run, or give every run `--round`. The two
such remits below can share a round. It is a round like any other: it counts toward
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
should do the same: they are sent the title and the abstract, nothing else, and asked two
things:

- what they conclude, in a sentence or two, as they would put it to a colleague;
- whether the abstract carries a caveat that would change that conclusion. If it does, they
  quote it; if not, they say what the conclusion would turn on.

This is not the desk editor's remit, which reads the whole paper and asks whether the
abstract matches it. This reader cannot compare the two, and that is what makes the reading
worth having.

Read it by route A only, since `review --run` sends every manuscript file. Put the title and
abstract in the brief of a fresh agent, or give them to a person who has not read the paper.
Never ask the context that wrote them: it knows what the abstract leaves out. Route A begins
by reading the whole manuscript, which this reader must not do, so if your tool cannot start
a fresh agent and no person is at hand, leave this remit out. Give it an id
such as `abstract-alone` and the remit "what a reader of the title and abstract alone
concludes, and whether the abstract carries the caveat that would change that conclusion".
If the manuscript is in several files and another reader of the same round, such as citation
support, lists them all, keep under `file_sha256` only the file that holds the abstract, as
step 2 of the skill says for a reader of some of them. Alone in its round, this reader keeps
the whole list: a round stays incomplete while a file is on nobody's list.

The reading's summary is that conclusion, and its verdict is on the abstract, not on the
paper. Its findings are about the abstract too: a caveat the
conclusion turns on that the abstract leaves out, or places where a reader passes over it.
Keep the reader to that. Given the abstract and a remit about the whole paper, a reader lists
what the paper might lack, and rates it major, without having seen it; those findings are
not this reader's to make.

Once the reading is sealed, set its conclusion beside the Results. Where they support less
than it says, the abstract has to change, even if the reader found no caveat missing: what
this reader concluded is what a reader of the abstract will conclude. No gate makes this
comparison and no record holds it, so give the author the conclusion and the Results it goes
beyond, and let the next round read the abstract they write.

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
