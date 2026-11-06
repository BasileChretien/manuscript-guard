<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/img/brand/banner-dark.svg">
    <img src="docs/img/brand/banner-light.svg" width="860" alt="Vord before a manuscript, blocking each mistake in turn with the gate that catches it, while a co-author reads.">
  </picture>
</p>

# manuscript-guard

[![PyPI](https://img.shields.io/pypi/v/manuscript-guard)](https://pypi.org/project/manuscript-guard/)
[![CI](https://github.com/BasileChretien/manuscript-guard/actions/workflows/ci.yml/badge.svg)](https://github.com/BasileChretien/manuscript-guard/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](pyproject.toml)
[![Licence: MIT](https://img.shields.io/badge/licence-MIT-blue)](LICENSE)
[![Status: alpha](https://img.shields.io/badge/status-alpha-orange)](#status)

**Every number traceable to its source.**

From research idea to a reproducible, submission-ready manuscript: AI assistance, human
oversight, deterministic checks. manuscript-guard holds a scientific manuscript to the
analysis that produced it, the sources it cites and the plan it was written to. An agent can
do much of the work; a person makes the calls; no check asks a model anything, and everything
runs without an agent. It keeps a record of the scientific judgements made: it does not make
them.

**[Check a paper in your browser](https://basilechretien.github.io/manuscript-guard/audit/)** ·
**[Start a paper](docs/getting-started.md)** ·
**[See it catch a mistake](#see-it-catch-a-mistake)** ·
**[For supervisors and groups](docs/teams.md)**

## See it catch a mistake

On the worked example: one binding of the abstract replaced by the number it stood for,
`check` failing on it, the number bound again, and `check` passing.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/img/demo-dark.svg">
  <img src="docs/img/demo-light.svg" width="860"
       alt="manuscript-guard check prints [FAIL] G2 manuscript/main.md:11:17, '4,000' is not bound to any source. The author replaces 4,000 with {{results.cohort.n_reports}} on line 11, and check runs again: stage: drafting (writing the manuscript against results that exist); numerical provenance, checked: G2, G3, G7, G8: 0 failing, 1 warning; and its last line, 0 failing, 13 warnings.">
</picture>

## What it does

It keeps a study to its record, from the analysis plan to the published paper. The plan is
written before the analysis and frozen when the first results are written. Every number in
the manuscript is bound to the result or the published sentence it came from, or justified
as a convention of writing. The analysis can be run again and its results compared value by
value. The checks and approvals that need a person are recorded, with who gave them and
when, for a co-author, an editor or a reader to look at later.

It holds the study to the guidelines it answers to, each read from its source rather than
remembered: the reporting checklist of its design (CONSORT 2025, SPIRIT 2025, STROBE,
RECORD, PRISMA 2020, TRIPOD+AI and others), the journal's instructions for authors, ICMJE's
recommendations, the study's registration and the norms on text recycling. Each is checked
on every run from the first draft, so what a guideline asks is found while there is still
time to do it, not the night before submission ([the guidelines](#the-guidelines-it-answers-to)).

Claude Code, Codex or another agent tool, with a skill for each step, drafts the plan,
writes and runs the analysis, binds the numbers, drafts the prose and fixes what the check
finds, and `manuscript-guard next` tells it, or you, what to do now. The seventeen gates are
deterministic code that runs offline and in CI; two of them read a recorded review, of each
figure and of the manuscript, which a person or a model may have written
([principles](docs/principles.md)). What only a person should do is put to a person: an
author's approval, a statistician's sign-off, an attestation that a value was read in its
source, sending the manuscript to a model provider, releasing what an analysis wrote from the
data, publishing a deposit. Co-authors are asked, one page each, what no gate can see:
whether a sentence says what its source says.

Numbers are where it is strictest. A number in a paper comes from one of three places: your
results, the literature, or a convention of scientific writing. A number from your analysis
is a binding into a results file that your Python or R code writes; a number from the
literature is a binding into a ledger, beside the sentence of the stored source it was quoted
from; anything else has to be justified. Change the analysis, run it again and rebuild, and
every bound number in the paper and its supplement follows. A number with no source is a
finding of the check, not something left for a reviewer to notice.

> **What it rests on so far.** It is alpha.
>
> - **A real paper.** One manuscript, a narrative review by the toolkit's author, has been
>   through `check`, `build`, `verify`, which ran the analysis again and reproduced each of
>   its 1,483 values, and `import` of two rounds of edits made in Word, by script rather
>   than by a co-author.
> - **A measured set.** G7's reference checks, on the 740 references of 16 published
>   open-access pharmacology and epidemiology papers: as published, 1.49 false alarms per
>   100 references in all, of which 0.68 from the search by title and the comparison of
>   authors; 1.08 from those two with every DOI and PMID taken out.
> - **Not measured.** How much of a study an agent can carry with it, and whether the
>   research is better for it. No study has yet gone from its plan to publication with the
>   toolkit.
>
> [Status](#status) has the rest.

## Two ways in

**I have a manuscript.** `audit` checks a paper written some other way: its numbers against
each other and against the analysis outputs you give it, its Abstract against its Results,
its words and its reference list. The
[audit page](https://basilechretien.github.io/manuscript-guard/audit/) runs it on a .docx in a
web browser, and the paper is not uploaded ([how it works](docs/audit-page.md)).
At a terminal, with [uv](https://docs.astral.sh/uv/) and nothing else installed:

```bash
uvx manuscript-guard audit paper.docx
```

**I am starting a project.**

```bash
pip install manuscript-guard
manuscript-guard init my-paper
cd my-paper
manuscript-guard next
```

`init` writes the project, and `next` says what to do now, with the command to run, from the
analysis plan on. [Install](#install) has what else a build needs, and
[Quick start](#quick-start) the worked example.

## Who it is for

Guided, not replaced: three kinds of user, using the same tool differently.

- **PhD students and researchers new to a step.** `manuscript-guard next` and the skills walk
  you through each step and say what each check asks. The methods still need a supervisor's
  or a statistician's judgement, and the tool records their sign-off.
  [Getting started](docs/getting-started.md) says what you need and what to do first.
- **Experienced researchers.** Less copying of numbers and checking by hand; the analysis
  reruns (`verify`); co-authors stay in Word (`import`).
- **PIs and research groups.** The same stages and checks across a group's papers; a GitHub
  Action that runs them in each paper's repository; and the records of who approved what
  ([for supervisors and research groups](docs/teams.md)).

## Who does what

| Who | What |
|---|---|
| An agent, through the skills | drafts the analysis plan, writes and runs the analysis, binds the numbers, drafts the prose, fixes what `check` finds |
| The gates | decide from the records, offline and in CI, and ask no model anything |
| A person | answers the findings only a person may close, among them: an attestation that a value was read in its source, a judgement that a passage supports its sentence, an answer to a co-author's comment or to a major finding of a review; approves the manuscript (`approve`); signs off what is theirs to close (`sign`); answers a co-author's page of things to confirm (`checker`); is asked before the manuscript is sent to a model provider (`review --run`) and before a deposit is published (`deposit --publish`) |

## What it covers

- **The plan and the data.** An analysis plan, a data dictionary, the record of the datasets
  considered and the one chosen, the study's registration; the data held, where need be, in
  a folder the operating system keeps from the agent, with a synthetic copy to write the code
  against ([the vault](docs/vault.md)).
- **The analysis.** Results published by an emitter for Python or R, with the scripts and
  inputs they came from, or taken in from what a script writes on its own
  ([harvest](docs/harvest.md)); models held to their variables; `verify` runs it all again.
- **The manuscript.** Markdown built to Word, or LaTeX compiled to a PDF
  ([LaTeX](docs/latex.md)); tables and figures placed by key and numbered by the build; live
  Zotero citations.
- **The check.** Seventeen gates, from the numbers to the Methods against the code, the
  references, the figures, the journal's rules ([journal profiles](docs/journal-profiles.md)),
  the reporting checklist and the language. A finding fails from the stage at which it
  starts to matter ([stages](docs/stages.md)), and `next` says what to do about it
  ([what to do next](docs/next.md)).
- **Co-authors and review.** Edits and comments in Word brought back to the source
  ([co-authors](docs/co-authors.md)); a review panel of people, or of models from several
  providers ([review panel](docs/review-panel.md)); replies to the journal's reviewers held
  to the revision.
- **Submission and after.** The submission pack, the publisher's proof checked against it,
  the code and results packaged and deposited at Zenodo or OSF ([deposit](docs/deposit.md)),
  posts and summaries held to the paper ([communicate](docs/communicate.md)).
- **Other people's papers.** `audit` and `compare` read a manuscript written some other way,
  a PDF among them, on your own computer: an editor's or a referee's
  ([refereeing](docs/refereeing.md)), or your own from before ([audit](docs/audit.md)).

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/img/loop-dark.svg">
  <img src="docs/img/loop-light.svg" width="860"
       alt="The analysis writes results; the manuscript binds to them and to a literature ledger; check runs seventeen gates against the journal's rules and a reporting checklist; build writes the .docx; import brings a co-author's Word edits back to the manuscript.">
</picture>

## What it catches

Vord, the project's guard, stands for the gates, and each villain for a mistake that one of
them catches, named with that gate. Five are rows of the table below. The Plan Rewriter changes
the analysis plan after the first results and says nothing under Deviations, which G12 warns
of. What no gate sees is drawn as a shadow ([the part no gate can check](#the-part-no-gate-can-check);
[the character sheet](brand/README.md)).

| <picture><source media="(prefers-color-scheme: dark)" srcset="docs/img/brand/stray-number-dark.svg"><img src="docs/img/brand/stray-number-light.svg" width="72" alt=""></picture> | <picture><source media="(prefers-color-scheme: dark)" srcset="docs/img/brand/forger-dark.svg"><img src="docs/img/brand/forger-light.svg" width="72" alt=""></picture> | <picture><source media="(prefers-color-scheme: dark)" srcset="docs/img/brand/ghost-citation-dark.svg"><img src="docs/img/brand/ghost-citation-light.svg" width="72" alt=""></picture> | <picture><source media="(prefers-color-scheme: dark)" srcset="docs/img/brand/impostor-doi-dark.svg"><img src="docs/img/brand/impostor-doi-light.svg" width="72" alt=""></picture> | <picture><source media="(prefers-color-scheme: dark)" srcset="docs/img/brand/plan-rewriter-dark.svg"><img src="docs/img/brand/plan-rewriter-light.svg" width="72" alt=""></picture> | <picture><source media="(prefers-color-scheme: dark)" srcset="docs/img/brand/stale-methods-dark.svg"><img src="docs/img/brand/stale-methods-light.svg" width="72" alt=""></picture> |
|:-:|:-:|:-:|:-:|:-:|:-:|
| The Stray Number, G2 | The Forger, G1 | The Ghost Citation, G7 | The Impostor DOI, G7 | The Plan Rewriter, G12 | Stale Methods, G9 |

In the table below, each row names the stage from which its finding fails the run. Before that stage the
finding is printed and counted, and the run passes: a new project starts at `design`,
where the manuscript can wait ([stages](docs/stages.md)).

| What went wrong | What `check` names | Fails from |
|---|---|---|
| A number was typed into the text where a result should be bound | the number, with its line and column | `drafting` |
| A results file was edited by hand | the file, which no longer matches what the analysis wrote | `analysis` |
| The script that wrote a results file, or an input it declared, changed afterwards | which of them, and the script to run again | `analysis` |
| A value taken from a paper is not in the sentence quoted as evidence for it | the value and the quote; the quote itself has to be in the stored source | `drafting` |
| A cited work has been retracted | the reference, and the registry that says so, from what `lookup` recorded | `drafting` |
| A DOI or PMID names another work than the one cited | the reference, and what the registry has under it | `internal-review` |
| A number was typed into text that a figure draws | the line of the figure's script | `drafting` |
| A model does not suit its variables: a binary outcome under a linear model, a categorical code entered as one slope, a reference other than the one declared, a level with no events | the model and the variable | `analysis` |
| The analysis changed after the Methods were last read against it | the files that changed | `internal-review` |
| A count below the data custodian's minimum is printed | the count and its key | `internal-review` |
| A reporting checklist item (CONSORT, STROBE, PRISMA and others) is not addressed | each item still open | `internal-review` |
| The journal's word limit, a required section or a required statement is missed | which one | `internal-review` |
| A co-author's comment in Word has no answer | the comment, by its file and line or by its words | `submission` |
| A registered outcome is reported nowhere, and the Deviations do not say why | the registration and the outcome | `submission` |
| A reply to a reviewer claims a revision that was not made | the point | `submission` |

`check` knows that a results file is out of date from digests: of the script that wrote
it, and of the inputs that script declared. It does not follow imports, so a change in a
helper module fails the run only where the script lists that module among its `inputs`.
Left unlisted, a source file under `analysis/` that is newer than the results gets a
warning, and the run passes.
`manuscript-guard verify` asks the other question. It runs the analysis again into a
scratch copy and compares every value, which takes as long as the analysis does, and is
what catches a result that changed while its file did not.

This is the finding for the first of those, on the worked example, after one binding in
the abstract was replaced by the number it stood for. The line that opens the output and
what follows the finding are left out:

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/img/check-dark.svg">
  <img src="docs/img/check-light.svg" width="860"
       alt="manuscript-guard check prints: FAIL G2 manuscript/main.md:11:17, '4,000' is not bound to any source, with the line it is on and a hint to bind it with a results or literature key.">
</picture>

And for the second, after one value in a results file was changed by hand. `...` stands
for a line left out, and other findings follow from the same edit:

```text
  [FAIL] G1 results/01_disproportionality.json
         01_disproportionality.json has been modified since the analysis wrote it
         ...
         hint: results are machine-written; change the analysis and re-run it rather than editing this file
```

## The guidelines it answers to

| Guideline | What is checked | Gate |
|---|---|---|
| Reporting checklists: CONSORT 2025, SPIRIT 2025, STROBE, RECORD, RECORD-PE, PRISMA 2020, TRIPOD+AI, STARD 2015, CHEERS 2022, ARRIVE 2.0, READUS-PV, and SANRA for a narrative review | each item says where it is addressed, or why it does not apply; a warning where the study design declared has none of its guidelines, and where a guideline's authors have replaced it | G5 |
| The journal's instructions for authors | each rule quoted from the journal's stored page: limits, sections, required statements, the data availability statement against the data policy, artwork, the boxes beside the abstract | G4 |
| ICMJE's recommendations | tables and figures cited in the order of their first citation; an earlier output of the same data disclosed | G2, G8 |
| The study's registration, at ClinicalTrials.gov, the EU PAS register, OSF or ISRCTN | made before the study started, or said to be retrospective; each registered outcome reported in the registry's words and role, or its absence said | G12 |
| Text recycling (Text Recycling Research Project; COPE and BioMed Central) | passages shared with the authors' earlier papers, with the part of the paper each is in | G7 |
| Methods standards: the ENCePP Guide, target trial emulation, ROBINS-I, RoB 2, PROBAST+AI, ROBIS and others | a method taken from a similar study is appraised against one, and taken on a person's decision | G12 |
| The data custodian's rules | no count printed below the custodian's minimum; a restricted input never packaged | G2, `package` |

**How it keeps up.** A checklist is downloaded from its authors' site (`fetch`) and turned
into items by a recipe (`transcribe`), never typed from memory; a new edition is a new
recipe, and the items are made again from the new document. A journal's page read again
(`journal --reread`) shows which rules changed. `check` lists each item still open at every
run, so the checklist is kept from the first draft rather than filled in at the end. How much
time this saves has not been measured.

**What it does not do.** G5 holds that each item names a place or a reason, and warns where
the place is no heading of the manuscript; whether the text there does what the item asks is for a reader, and the starter
panel of a review round has a reporting-guideline reviewer for it. The checklists are not shipped, since each has its own licence:
`fetch` and `transcribe` make each one once, on your machine. [The guidelines](docs/guidelines.md)
has each row in full.

## How it works

The manuscript source is Markdown. Numbers appear in it as bindings:

```markdown
The database contained {{results.cohort.n_reports}} reports, of which
{{results.cohort.n_drug_reports}} named example-drug. The reporting odds ratio was
{{results.ror.point}} (95% CI {{results.ror.ci_low}} to {{results.ror.ci_high}}).
```

A value from a paper is bound the same way, `{{lit.background.class_ror}}`, to an entry of
`literature/ledger.yaml` that holds the value, the sentence it was quoted from and the stored
copy of the source. A table or a figure is placed by its key, `{{table.baseline}}`, and
pointed at by it: `{{ref.table.baseline}}` prints "Table 2" if it is the second table the
main text places, and the number follows the table when it moves. In LaTeX the binding is
`\mg{results.cohort.n_reports}` ([LaTeX manuscripts](docs/latex.md)).

Your analysis publishes those values through an emitter, which records where they came
from. There is one for Python and one for R, and anything that can write JSON can take part:

```python
from manuscript_guard.emit import Emitter

em = Emitter(__file__, inputs=["data/reports.csv"])
em.value("cohort.n_reports", 4000)
em.value("ror.point", 3.4211, digits=2)
em.write()
```

An output a script writes on its own, a `.csv`, `.tsv` or `.json`, is taken in by
`harvest` ([harvest](docs/harvest.md)).

Then three commands do most of the work:

```bash
manuscript-guard next      # what to do now, with the command to run
manuscript-guard check     # every gate, against the source
manuscript-guard build     # the .docx, with live Zotero citations
```

`check` reads the **source**, where a binding is still visible, and not the rendered text,
where every number looks alike. The rule is short: in manuscript source, a bare number is a
defect unless it is a recognised convention (a 95% confidence interval) or a pointer
(Table 1). The check also runs the other way: a value the analysis declares as quoted,
which nothing quotes, fails too.

`build` writes the .docx from the Markdown every time, so the document is never edited and
nothing is carried across by hand. With Zotero open it writes live Zotero citation fields
that Word's plugin adopts. Without it, `--offline` formats the citations from a committed
`references.bib`, which is what CI and a co-author without your library get.

## What is checked

Seventeen gates, each code that decides from the project's records, offline and in CI.
`check` ends by grouping what they did by what it is about, and the same groups sort them
here:

| What it is about | Gates |
|---|---|
| computational reproducibility | G1 |
| numerical provenance | G2, G3, G7, G8 |
| reporting completeness | G4, G5, G13 |
| methodological validity | G9, G12, G15 |
| data | G16 |
| literature | G7 |
| review | G10, G11 |
| language and writing | G6, G14 |

G7 is in two groups, and G0, which holds that the manuscript can be read at all, is in none.
[What is checked](docs/gates.md) has what each gate holds, and what `check` says in words of
what no gate decides. A finding fails from the stage at which it starts to matter, and
until then it is printed and counted without failing the run ([stages](docs/stages.md)).
What each gate guarantees, and why it is built that way, is in
[principles](docs/principles.md).

## The part no gate can check

Every gate above asks whether a number is the number the analysis produced, or whether a quote
is really in the stored source. None can ask what a reader of that source asks: **does the
sentence say what the document says.** A value can be right, its quote can be right, and the
sentence around it can still name the wrong denominator, subgroup or year with every check
passing. On the first manuscript written with this toolkit, that is what happened, and a
co-author reading one item against one quote is what found it.

Such a mistake is drawn as a shadow: Vord's sword passes through it, so Vord calls a co-author.

| <picture><source media="(prefers-color-scheme: dark)" srcset="docs/img/brand/confirmation-bias-dark.svg"><img src="docs/img/brand/confirmation-bias-light.svg" width="72" alt=""></picture> | <picture><source media="(prefers-color-scheme: dark)" srcset="docs/img/brand/data-leakage-dark.svg"><img src="docs/img/brand/data-leakage-light.svg" width="72" alt=""></picture> | <picture><source media="(prefers-color-scheme: dark)" srcset="docs/img/brand/co-author-dark.svg"><img src="docs/img/brand/co-author-light.svg" width="72" alt=""></picture> |
|:-:|:-:|:-:|
| Confirmation bias | Data leakage | The co-author |

```bash
manuscript-guard checker build --all                    # one file per author, to send each
manuscript-guard checker import --answers a.json b.json # what they said, into checks/decisions.csv
manuscript-guard checker status                         # outstanding, stale, and who disagrees
manuscript-guard checker recap                          # who checked what, into checks/recap.md
```

`checker build` writes one file for each person, which opens in any current browser, offline,
with nothing installed and nothing sent anywhere by the page. It asks about the values quoted
from the literature, the sentences that cite something, each Methods text beside the code it
points at, the references and the authors. Each answer carries the digest of what its maker
saw, so an answer about a sentence that has changed since no longer counts as agreement, and
`checker recap` writes who checked what, tamper-evident by an unsigned hash chain over the
record. What this gives you is a record of who looked, at what exactly, when, and what they
said. It is not a proof that they read it correctly, and nothing here checks their reading.

The rest of a co-author's part is in Word. `import` brings their edits back into the source
and files each of their comments as a finding to answer; `review --suggestions` writes the
edits a panel's findings suggest into a Word document as tracked changes, for the author to
accept or refuse; `approve`
records an author's approval of the manuscript as it stands; and `build --marked-up` writes
the revision with every change since the version the journal received.
[Working with co-authors](docs/co-authors.md) has the detail of each.

## Install

Python 3.10 or later:

```bash
pip install manuscript-guard
manuscript-guard --version
```

To audit one paper without installing anything, [uv](https://docs.astral.sh/uv/) runs it in
one line, fetching a Python if there is none:

```bash
uvx manuscript-guard audit paper.docx
```

Or, with no terminal at all, [the audit page](docs/audit-page.md) runs `audit` on a .docx in
a web browser, and the paper is not uploaded.

To build a .docx you also need [pandoc](https://pandoc.org/installing.html). Zotero, R, and
`pdftotext` or pypdf for reading PDFs, are needed only for particular things, and the tool
says which when you reach it. [Installing and upgrading](docs/install.md) has the table of
optional tools, the upgrade commands, how to install from the repository, and the R
emitter.

## Quick start

Start a paper:

```bash
manuscript-guard init my-paper
```

That writes a project with a `paper.yaml`, an analysis plan to fill in, a manuscript and an
`AGENTS.md` that gives any agent working there the rules on one page.

Or run the worked example first. [`example/`](example/) is a synthetic pharmacovigilance
study that exercises every gate but G13, having no revision round. It is in the repository and not in the installed package,
so it needs a clone, a Python that has `manuscript_guard` installed, statsmodels for its
model and matplotlib for its figure:

```bash
git clone https://github.com/BasileChretien/manuscript-guard
cp -r manuscript-guard/example my-example && cd my-example
python analysis/00_simulate.py && python analysis/01_disproportionality.py && python figures/forest.py
manuscript-guard check
manuscript-guard build --offline     # writes build/manuscript.docx and build/supplementary.docx
```

Then type a number over one of the bindings in `manuscript/main.md` and run `check` again.
A different matplotlib version draws a slightly different figure, and `check` then lists
the figure's recorded review as stale; that is `INFO` until the `internal-review` stage.

When a finding surprises you, `manuscript-guard explain manuscript/main.md` prints every
number in the file and the rule that classified it.

## Commands

`manuscript-guard --help` lists the commands in groups, and [Commands](docs/commands.md) has
each with what it does. Each takes `--help`.

- **[Setup & Guide](docs/commands.md#setup--guide):** start a project (`init`), say what to
  do now (`next`), and write a setting of `paper.yaml` (`set`).
- **[Checking & Audit](docs/commands.md#checking--audit):** run every gate (`check`), audit a
  paper written some other way (`audit`), and set a revision beside the version before it
  (`compare`).
- **[Analysis & Data](docs/commands.md#analysis--data):** run the analysis again and compare
  every value (`verify`), take in what a script writes on its own (`harvest`), and register
  the folder, kept from the agent by the operating system, that holds the data (`vault`).
- **[Literature](docs/commands.md#literature):** ask the registries about each cited work
  (`lookup`), propose works a claim could cite (`search`), and copy the cited works from
  Zotero (`sync-sources`).
- **[Co-Authors & Review](docs/commands.md#co-authors--review):** a review panel (`review`), a
  co-author's page of things to confirm (`checker`), their Word edits brought back
  (`import`), and approvals and sign-offs (`approve`, `sign`).
- **[Build, Release & Communicate](docs/commands.md#build-release--communicate):** the .docx
  or PDF (`build`), the submission pack (`submit`), the code and results packaged and
  deposited (`package`, `deposit`), and posts held to the paper (`communicate`).

## Agent tools

The pip package is the whole guarantee and needs nothing else. An agent tool adds two
things: skills, which carry an agent through the steps that need judgement, and hooks,
which catch a mistake at the moment it is made and put to you the calls only you may make.
[Agent tools](docs/agent-tools.md) says what each tool enforces and what it does not.

### The Claude Code plugin

This repository is its own plugin marketplace:

```bash
claude plugin marketplace add BasileChretien/manuscript-guard
claude plugin install manuscript-guard@manuscript-guard
```

Start with `guide`, which works through the paper with its author from `manuscript-guard
next`, and `project-setup`, which starts the project; most of the other skills name the
finding codes that should send you to them. [The skills](docs/agent-tools.md#the-skills)
lists each one and what it is for.

Five hooks: one line on the project's state when a session starts, ending with what
`manuscript-guard next` puts first, and again at the end of a turn that changed the
manuscript or what it rests on; a refusal to edit files that are machine-written; a note on
the numbers just saved in a manuscript file; and the submission check before a command that
looks like a submission. An author's approval, a named person's sign-off, an attester named
in `literature/attested.yaml` and a panel sent to the models without asking are each put to you before they
run, and refused where nobody can be asked. Where the data are held in a
[vault](docs/vault.md), the session's first line says whether the agent can read them, and a
command that names their folder is refused while it can.

### Codex

Codex installs the same plugin, with the same skills and hooks:

```bash
codex plugin marketplace add BasileChretien/manuscript-guard
codex plugin add manuscript-guard@manuscript-guard
```

By Codex's documentation, it runs a hook only after you have trusted it, under `/hooks`.

### Gemini CLI, Mistral Vibe, Kimi Code CLI and other tools

By their own documentation these read skills from a folder, and one command copies the
skills there:

```bash
manuscript-guard install-skills              # for you, in every project: ~/.agents/skills
manuscript-guard install-skills --project    # for one paper: .agents/skills in that project
```

There are no hooks under these tools. `check`, `build` and `submit` hold as they do
everywhere.

| | Skills | Hooks |
|---|---|---|
| Claude Code | plugin | five |
| Codex | plugin | five, once you have trusted them |
| Gemini CLI, Mistral Vibe, Kimi Code CLI | copy | none |

## More

| | |
|---|---|
| [Getting started](docs/getting-started.md) | for someone new to keeping a study in code: what you need, who decides what, the first hour, and what you still check yourself |
| [For supervisors and research groups](docs/teams.md) | one layout for every paper, the check on every push and its badge, co-authors, approvals and sign-offs, review panels, the data custodian's rules, and what stays the supervisor's |
| [Installing and upgrading](docs/install.md) | upgrades, optional tools, the R emitter |
| [Checking a paper in GitHub Actions](docs/github-actions.md) | the workflow `init --github-actions` writes: check on each push and pull request, the documents built where it passes, what CI cannot reach, and a badge that says the stage the check passes at |
| [Stages](docs/stages.md) | which findings bind when, from the analysis plan to submission |
| [The guidelines](docs/guidelines.md) | the reporting checklists, ICMJE, the journal's instructions, the registration, text recycling, methods standards and the custodian's rules: what each check holds, and what it leaves to a reader |
| [Working with co-authors](docs/co-authors.md) | edits and comments in Word, suggested edits as tracked changes, approvals, the marked-up revision, and the checker for what no gate can check |
| [Journal profiles](docs/journal-profiles.md) | the journal's rules quoted from its page: the boxes beside the abstract, a graphical abstract, what may be shared |
| [What to do next](docs/next.md) | `next`: the order it decides in, and its JSON for an agent |
| [Principles](docs/principles.md) | what the check guarantees, and why it is built this way |
| [What is checked](docs/gates.md) | each gate and what it holds, and what `check` says when it ends |
| [Commands](docs/commands.md) | every command, in the groups of `manuscript-guard --help`, with what it does |
| [Agent tools](docs/agent-tools.md) | Claude Code, Codex and the others: installing, updating, what each enforces |
| [A review panel read by several models](docs/review-panel.md) | internal review by people, an agent, or models from several providers |
| [LaTeX manuscripts](docs/latex.md) | writing in LaTeX, or sending a Markdown manuscript as LaTeX, and what does not read LaTeX yet |
| [Depositing the code and the results](docs/deposit.md) | the package, its citation files, its description as an RO-Crate, its companion page, the bundles `deposit` stages, and what it sends to Zenodo and OSF when asked |
| [Communicating the paper](docs/communicate.md) | the brief of the paper's own sentences, the graphical abstract drawn from it, and every post or summary held to both |
| [Auditing a paper you already wrote](docs/audit.md) | one command for a manuscript with no bindings, how little a match means, and bringing a Word paper into a project |
| [For editors and reviewers](docs/refereeing.md) | a manuscript sent in confidence, a PDF among them, read on your own computer with nothing sent: a referee's audit, its causal words and its cited sentences, and an editor's against the journal's profile, its tracked changes and the names Word keeps, the authors named where the review is blind, and the self-citations counted; a revision set beside the version before it, with the response letter; the authors' package held to its own manifest; and a draft of your report with the findings and their places |
| [Data held apart from the agent](docs/vault.md) | the vault: the data in a folder the operating system keeps from the agent, the four setups that do that, most separating first, three traps, what the hooks refuse and what the agent tool's own rules cover; the analysis run on the data in a copy inside the vault, and what it wrote released on a person's word; the profile of each file and the synthetic copy drawn from it |
| [When manuscript-guard itself fails](docs/failures.md) | the one sentence a fault of the tool's own ends in, the record kept on your machine, and the variables that turn it off |
| [Supporting the project](docs/funding.md) | grants, collaborations and GitHub Sponsors, and the contributions that cost no money |
| [DESIGN.md](DESIGN.md) | the architecture, the reasons for its decisions, and the known gaps |
| [ATTRIBUTION.md](ATTRIBUTION.md) | the reporting guidelines' licences, and the one data file derived from another work |
| [SECURITY.md](SECURITY.md) | reporting a vulnerability, and what is in scope |

## Status

Alpha. The gates still change from week to week: interfaces, file formats and what a gate
reports can change without a migration path. Every round of review so far has found
something the round before had opened up.

What has run on real papers:

- **One real manuscript**, a narrative review by the toolkit's author, written with it since
  September 2026. On 2026-11-04, with 0.2.473, it went through `check`, `lookup`, `build`
  (live and offline), `verify`, which ran the analysis again and reproduced each of its
  1,483 values, and `import` of two rounds of edits made in Word 16 as a co-author would make
  them, by script rather than by a co-author. It stopped at the submission check, which asks
  for a review panel.
- **`audit`**, which reads a paper written some other way, has been pointed at one submitted
  paper, and what it found is recorded in DESIGN.md.
- **G7's reference checks** were measured on 2026-10-21 against the 740 references of 16
  published open-access pharmacology and epidemiology papers: as published, 1.49 false
  alarms per 100 references in all, of which 0.68 from the search by title and the
  comparison of authors; 1.08 from those two with every DOI and PMID taken out, so that each
  reference was searched for (DESIGN.md, "Measured on real papers").
- **G6's thresholds** for AI phrasing were set from how often it fires on 384 biomedical
  research articles of 2010 to 2022, written by people; no text written by a model was read.

The rest has run on the worked example and the test suite's inputs only: among it the review
panel (`review --run`), the co-author checker, `submit`, `proof`, `package` and `deposit`,
`communicate`, the vault and `compare`. No study has yet gone from its plan to publication
with the toolkit, and two things have not been measured: how much of a study an agent can
carry with it, and whether the research is better for it. What it claims rests on its tests
and on the measurements recorded in [DESIGN.md](DESIGN.md), under "What a claim rests on".

A passing `check` means that no finding due at the project's stage is open. At
`submission` that is what the tables above describe; at an earlier stage the findings not
yet due are printed and counted, and the run still passes. Neither is evidence that a
paper is right. What the toolkit cannot see is listed under "Known gaps" in
[DESIGN.md](DESIGN.md), because a gate whose limits are undocumented gets trusted beyond
them.

## Contributing without code

The most useful contribution now is a case where a gate is wrong, in either direction: a
false alarm or a miss, reported with the smallest text that shows it. The
[issue templates](.github/ISSUE_TEMPLATE/gate-got-it-wrong.md) ask for that, and
`manuscript-guard report-issue --about G2 --flagged --snippet "…"` (or `--missed`) writes the
report for you to read and post. A profile of a journal you submit to
([journal profiles](docs/journal-profiles.md)) and a recipe for a reporting checklist that
is missing are contributions too.
[CONTRIBUTING.md](CONTRIBUTING.md) says how, and [supporting the project](docs/funding.md)
lists the ways to help, with and without money.

## Citing

If you use manuscript-guard for a paper, the "Cite this repository" button on GitHub gives
the reference, from [CITATION.cff](CITATION.cff).

## Licence

The code is under the MIT licence. Vord, the emblem and the other drawings in `brand/` and
`docs/img/brand/` are under CC BY 4.0 ([the character sheet](brand/README.md)).
