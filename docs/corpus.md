# Measuring the gates on a corpus of real papers

The test suite holds each rule to the cases it was written for. It cannot say how often a
finding is right on papers nobody wrote for it. For that the tool is run over real papers,
a person judges each finding true or false, and every later build is measured against
those verdicts. `tools/corpus.py` does the running, the measuring and the gate. It is for
people working on manuscript-guard, not for authors of a paper.

The corpus stays out of the repository: real papers seldom have a licence that allows
copying them, and the verdicts quote their text. The tool finds it through the variable
`MANUSCRIPT_GUARD_CORPUS`, or `--corpus`.

## The corpus folder

```
corpus/<slug>/meta.json      where the paper came from, and which files are which
corpus/<slug>/files/         the paper as downloaded
report/packets/<name>.json   the findings that were judged, with the text they were judged by
report/judged/<name>.json    the verdicts
report/ledger.yaml           the author's decisions that re-judge a finding (below)
report/ties.yaml             each judged finding's key in a keyed run, written once by `tie`
report/ties-ambiguous.md     the judged findings `tie` left for the author to settle
report/ties-decided.yaml     the author's ties of those, read over ties.yaml
report/ties-untied.md        the judged findings no rule ties, which the matcher pairs
runs/<run>/<slug>/<report>.json   one run of one build: audit, audit-pdf, check, compare
builds/<sha9>/               a venv for each commit run, named by its sha's first nine characters
```

`meta.json` names the paper's `slug`, its `format` (`docx`, `pdf` or `latex`) and its `main`
file under `files/`, and may name a `pdf` of the same paper and a `v1`, an earlier version,
which `compare` sets beside the main file. Keep the SHA-256 of each file there too, so a paper
fetched again can be told from another. A slug is its folder's name, in letters, digits,
`.`, `_` and `-`.

Give the corpus folder its own git repository, if any, never a remote, and this
`.gitignore`:

```
corpus/*/files/
runs/
builds/
__pycache__/
CLAUDE.local.md
.claude/
*.log
```

The papers are other people's work, whose licences seldom allow passing them on, and each is
fetched again from its `meta.json` and checked against its SHA-256; runs and builds are made
again from a commit. The tool refuses a corpus folder inside the manuscript-guard checkout,
or inside the main working tree of the repository where the checkout is a git worktree, and
writes nothing there: `run` writes under the corpus's `runs/` and `builds/`, and
`measure` and `gate` write to standard output or to the `--out` and `--json` paths given,
which may not be inside the checkout either, since their lists quote the papers.

A packet is a list of papers, each with its `slug`, the `text` a judge reads, and `reports`:
for each of `audit`, `audit-pdf`, `check` and `compare`, the `findings` as that report's
`--json` gave them, and `totals`, the number of findings of each `gate/code` in that report
before any were left out of the sample. A verdict is `{slug, report, index, verdict}`, where `index` is the
finding's place in that report's list and `verdict` is `true`, `false` or `unclear`; any other
fields (`kind`, `why`, `useful`) are kept for people. Only true and false verdicts are counted.

The papers are downloaded files. The tool runs nothing with its working folder inside
`corpus/`, gives every command a time limit, and runs the build under `python -I`, which
imports nothing from the working folder or from `PYTHONPATH`.

## Judging

Run a build, put a sample of each code's findings for each paper in a packet, and give the
packets to judges with what each gate claims, from [What is checked](gates.md) and
[Auditing a paper](audit.md). A finding is true when what it says of the text holds, and
false when it does not or when its premise fails under the field's own conventions. Judges
who do not know which build gave a finding judge it more fairly. The verdicts are never
changed afterwards; a later decision goes in the ledger.

## Running a build

```bash
export MANUSCRIPT_GUARD_CORPUS=/path/to/corpus
python tools/corpus.py run origin/main --name main-7bda66a5e
python tools/corpus.py run feat/my-branch          # runs/<its sha's first nine characters>
```

`run` installs manuscript-guard at that commit into `builds/<sha9>/`, from `git archive` of
this checkout and not editable, and runs on each paper `audit --json`, `audit --json` of the
PDF, `compare --json` against version 1, and `check --json` in a project made with
`init --from` (Word) or `init --latex`. Each step has ten minutes; a step already run for
the same commit is not run again, so a run stopped halfway goes on where it stopped. A run's
folder holds one commit: `run.json` and each paper's `steps.json` name it, and a run under a
name another commit's run already has is refused, so that a gate never reads reports of a
commit other than the one named. Without `--name`, the run is named by its commit. `--only`
takes slugs, `--jobs` the number of papers at a time.

## The four states

`measure <run>` puts each judged finding in one state:

- **reported**: a finding of the same gate and code that is the same one, as a warning or a
  failure;
- **asked**: that finding as a note or a question, or a question at the same line of the
  same file that names what the old one was about;
- **elsewhere**: another code's warning or failure at the same line of the same file that
  names what the old one was about, or for G14 another code's finding about the same short
  form (a question about it counts as asked);
- **gone**: none of those.

The same one is found one to one within each paper's report, each step for every judged
finding before the next: the same message at the same place, the same context at the same
place, the same message and context, the same message, the same context, and last the same
word at the same place or in the same part of the paper, the Abstract, the main text or the
supplement, as the message names it. The word is what the finding is about: its short form;
else a test statistic with its value as typed, "t(29) = 2.05", "F(2, 55) = 0.62",
"chi-squared(1) = 3.84" or "z = 2.10", its spacing, its minus and its point (a dot or a middle
dot) free, or failing that the P it states, never its degrees of freedom alone; else its first
words in quotes; else its first number of two characters or more. Where another finding of
the code has the same context, among the judged ones or the new ones, a context counts only
where the new message names that word, and not at all where the finding names none, since two
findings of one sentence share a context; a context no other shares is the finding's own,
whatever its counts now, unless the two name different short forms or names. A finding that
lists forms must list the old one's. A finding that lists forms,
as G14's one question does, gives each form once. Where a judged finding was the only one of
its code in its report (`totals`) and its word tells it from the others of its code in the
packets ("%" stands in every `notation-percent`, so it does not), it is found again in the
only finding of its code in the new report that names the word, wherever that stands. A new
finding taken by one judged finding is taken by no other, and a question or warning at the
same line keeps a finding only where it names its word, is of another code, and no judged
finding took it. The same file is the same path inside the paper's folder or its project.

A finding a later build says under another code at another line, as a note, reads as gone,
and a person reading the list has to see that it is not lost ([DESIGN.md](../DESIGN.md),
"Known gaps").

The report gives verdict by state, then the same with the reading notices apart, the
precision of the paper's findings still loud (reported or elsewhere), each code with the
precision of what it reports, the true findings gone, and the false ones still loud.
`--json` writes the same, finding by finding.

### Reading notices

Some findings say how the tool read the paper, not what the paper says: a part not read, or
how one was read. Losing one is not losing a finding about the paper, and they are counted
apart. These are the codes:

| Code | What it says |
| --- | --- |
| `abbreviations-passed-over` | the short forms left undefined that the audit passed over, by its list |
| `abstract-not-compared` | the Abstract was not set against the Results, and why |
| `causal-words-not-read` | a file whose causal words were not read |
| `displays-not-compared` | the tables or figures of two versions were not compared |
| `document-unreadable` | a document the audit could not read |
| `headings-read` | how the headings of a paper with none in a heading style were found |
| `lookup-missing` | cited works never looked up in a registry |
| `no-headings` | a paper with no heading, read as one text |
| `not-audited` | a part read as the reference list, or a PDF's lines placed in no section |
| `nothing-read` | the audit read no number |
| `passed-over` | a file that no paper inputs, not read |
| `reference-unchecked` | cited works with no DOI or PMID that could not be checked |
| `script-not-read` | prose in a script the gates do not read |
| `statements-without-passage` | cited statements with no recorded passage of a work they cite |
| `table-not-read` | a table whose cells were not read |
| `tables-read-as-prose` | tables read as prose in both versions |
| `tex-refused` | LaTeX the reader refused |
| `tex-words-not-read` | LaTeX words G14 does not read |
| `unreadable` | lines not read as LaTeX, or a file not read |
| `version-not-numbered` | a version whose tables or figures could not be numbered |

## Pairing by key

Every finding `check --json`, `audit --json` and `compare --json` give carries a `key`,
`gate|code|subject|digest` ([DESIGN.md](../DESIGN.md), "A finding's key pairs two runs"). Where
both runs carry keys, a judged finding is paired by its key alone (Basile, 2026-11-19), and
its message, its line and its context play no part:

- **reported**: its key stands in the new run at a warning or a failure;
- **asked**: its key stands as a note or a question, or a question lists a form under it;
- **elsewhere**: another code's warning or failure has its subject and its digest, or a
  `successor` of the ledger applies;
- **gone**: none of those.

Only a key unique in both runs pairs as it is. Where a key stands more than once in either
run, it keeps its judged findings only where its count did not fall from the base to the new
run; where it fell, every judged finding under it is gone, since which one went cannot be
told. `measure` and `gate` list the judged findings under a repeated key, and those paired by a
key made from the context (`"key_from": "context"`, a code that names no subject yet), apart.
Where either run has no keys, as every run before #706 has none, a judged finding is paired by
the matcher above, as before.

The judged findings come from a run with no keys, so they are tied to keys once:

```bash
python tools/corpus.py run origin/main --name keyed-<sha9>
python tools/corpus.py tie main-2235bfe54 keyed-<sha9>
```

`tie` pairs each judged finding with a finding of the keyed run, a run of a build with keys on
the same papers, by the matcher above, and ties it to that finding's key only where the
pairing is one to one, of the same gate and code, by the same message or the same context at
its place, with no other candidate so and a key the keyed run does not repeat. Exact rules
tie more (Basile, 2026-11-20), and never where a key the keyed run repeats would be tied
alone:

- **A finding with no line** ties to the keyed finding of its gate and code with the same
  message in the same file, where that message is the only one of its code so in the
  paper's report in both runs.
- **A short form** whose candidate is a list naming it, whatever the pass that found it,
  ties to the list's entry for it in the same scope (`HR@main`), where that entry is the
  only one so and the form and scope are the only ones of its code so in the judged run;
  never where the form stands in two scopes and the judged message names neither.
- **A key family**: a judged finding whose candidates all share one key once the subject's
  ordinal is taken off (`xxxx#1` to `xxxx#4`), or all carry one repeated key, ties to that
  family, `family: true`. The count rule then reads the family's count: where it falls from
  the base, every judged finding tied to it is gone. Never where the candidates differ by
  more than the ordinal.
- **Twins of one verdict**: judged findings of one report alike in gate, code, message and
  place, of one verdict, with as many distinct candidate keys as there are of them, tie one
  to one, the candidates in order of their place (of their keys where one has no column) and
  the judged findings in order of index. Their verdict is one, so the order changes no
  measure. Never where their verdicts or their numbers differ.

Each tie goes to `report/ties.yaml`, `{slug, report, index, key, how}` and `family` for a
family, under the name of the keyed run. A judged finding no rule settles, with several
candidates or a repeated key, goes to `report/ties-ambiguous.md` with its verdict, its message
and the candidates' keys and messages, for the author to decide by hand. A decision goes in
`report/ties-decided.yaml`, a list of `{slug, report, index, key, by, date}`, the key null
where no keyed finding is the judged one (it then reads gone in a keyed run) and `family:
true` for a key family; `measure` and `gate` read it over the ties, and refuse a decision
whose judged finding is not one of the judged set or whose key is not in the run of the ties.
The rest, with no candidate, a candidate another judged finding took, a weaker pass or a
finding of another code, go to `report/ties-untied.md` and stay for the matcher.
`tie` changes no verdict and no decision of the ledger. `measure` and `gate` read the ties for
a keyed run: a tied finding is paired by its key, its count held to the one in the run the
ties were made in (`measure`) or in the base (`gate`), and an untied one by the matcher, among
the findings no key took.

## The ledger

`report/ledger.yaml` holds the author's decisions that change what a finding should be:

```yaml
decisions:
  - id: placement-marker-no-slot
    date: 2026-11-11
    by: the author
    what: "[INSERT FIGURE 2]" is a placement marker, not an unfilled placeholder
    source: DESIGN.md, "A placement marker is no slot"
    rejudge:
      verdict: "false"
      findings:                       # by key ...
        - {slug: pdf-socio-A3, report: audit, index: 3}
      match:                          # ... or by a matcher on the judged finding
        - {gate: G6, code: model-artefact, message: '\[INSERT FIGURE \d+\]'}
  - id: abstract-question-successor
    date: 2026-11-16
    by: the author
    what: the audit asks where no Abstract or no Results is found
    source: "#697"
    successor:
      from: audit/abstract-not-compared
      to: [audit/question-no-abstract, audit/question-no-results]
      scope: paper
```

Each decision has an `id`, a `date`, who made it (`by`), one line on `what` it decides, its
`source` (a pull request or a section of DESIGN.md), and one of two kinds. A `rejudge` gives
the findings it names a new verdict, by key or by a matcher of `gate`, `code`, `slug`,
`report` and a regular expression on the `message`; the verdict file is left as it was. A
`successor` says that a finding about the whole paper was replaced: where the finding is gone
and the same paper's same report has one of the codes in `to`, it counts as asked. A
decision is the author's, with its source; the ledger is never written to say that a finding
the tool stopped giving was wrong because the tool stopped giving it.

## The gate

```bash
python tools/corpus.py gate main-7bda66a5e 1a2b3c4d5 --out "$MANUSCRIPT_GUARD_CORPUS/runs/1a2b3c4d5/gate.md"
```

`gate <base-run> <new-run>` puts every judged finding in its state at both, with the ledger
applied, and exits with 1 when a finding judged true, about the paper, is kept at the base
(reported, asked or elsewhere) and gone in the new run. A finding the ledger re-judges false
is not true any more, and one a successor covers is asked, so neither blocks. It lists
without failing the true findings that came back, those reported before and asked now, the
reading notices that changed, the false findings that became loud, and, by code, the
warnings and failures that no judged finding accounts for at either run. The Markdown folds
the long lists, so it can go in a pull request's description.

A pull request that changes a rule reading text runs `run` on its commit and `gate` against
main's run. A true finding lost blocks it, unless the author's decision in the ledger covers
it.
