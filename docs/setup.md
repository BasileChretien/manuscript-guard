# Starting a paper in conversation

A project needs a dozen decisions on its first day: how the manuscript is written, its title
and English, the study's design and reporting guideline, the journal, the authors, the
analysis language, where the data are, the registration, the repository. `manuscript-guard
setup` asks them and writes the project from the answers. With an agent tool, you answer in
conversation and never type a command; without one, you write the answers in a file.

The authors make every decision. The tool decides which questions are still open and writes
what was answered. An agent puts the questions to you and records your answers, and chooses
nothing.

## With an agent tool

Say to the agent that you want to start a paper with manuscript-guard. The project-setup
skill (Claude Code, Codex, and the tools [`install-skills`](agent-tools.md) copies the skills
to) then:

1. runs `manuscript-guard setup questions --json` in the folder;
2. puts each open question to you. Where the tool has question boxes (Claude Code), each is one
   decision with two to four options, the recommended one first; elsewhere they are numbered.
   A question whose answer is text (the title, the authors) is asked in words. The study's
   design is asked by having you describe the study, then offering the three designs that fit
   it best;
3. writes each answer into `design/setup.yaml` with its file tools, as you gave it;
4. asks again until nothing is open, reads every answer back to you in plain words
   (`setup apply --dry-run`), and on your yes writes the project (`setup apply`);
5. tells you what was written and why, what this machine lacks for the analysis, and what
   comes next.

## Without one

```bash
manuscript-guard setup questions            # what is still open, with the options
manuscript-guard setup apply --dry-run      # once design/setup.yaml answers them all
manuscript-guard setup apply
```

## The questions

Each question's id is the place its answer goes in `design/setup.yaml`. A question the folder
already answers is not asked: a `paper.yaml` that declares an English, R scripts in
`analysis/`, a filled `authors.yaml`. `later` puts a decision off, and `manuscript-guard next`
asks it when it is due.

| Id | Asks | Writes |
|---|---|---|
| `start` | Markdown, LaTeX, or a Word paper in the folder | the project, as `init`, `init --latex` or `init --from` makes it |
| `title` | the working title | `title` in paper.yaml and, in a project under way, the manuscript's header where it is `init`'s own |
| `language` | British English, American English, another language | `english_variant`; none for another language, whose writing checks do not apply |
| `study_type` | the design: you describe the study, and three designs that fit are offered | `study_type` |
| `reporting_guideline` | the guidelines of that design, each by its recipe's name (CARE-2013, TRIPOD+AI), or another | `reporting_guideline` |
| `journal` | a profile the project has, a journal named, help choosing, or later | the profile started from the template, and `target_journal` |
| `authors` | each author, in byline order: name, affiliations, corresponding author, ORCID, e-mail | authors.yaml |
| `declarations` | each author's funding, competing interests and CRediT roles, now or later | the authors' entries |
| `statistician`, `ethics_lead` | who signs off G15's warnings; who holds the ethics approval, with its reference | `roles` in authors.yaml |
| `analysis` | Python, R, another language, not decided | nothing; `apply` checks the machine for it |
| `data.where` | in the project, held apart from the agent, at a site, not obtained yet | see the next four |
| `data.folder`, `data.publishable` | the folder, and whether the data may be published | the folder in `.gitignore` where they may not |
| `data.minimum_cell_count` | the smallest count the custodian lets be published | `custodian.minimum_cell_count` |
| `registration` | each registration's identifier, none, or later | `registration` |
| `stage` | where the work has got to, for a paper written already or an analysis under way | `stage` |
| `repository.git` | whether the folder becomes a git repository | `git init` |
| `repository.visibility` | a public site, a private one, nowhere | nothing |
| `repository.sources_in_git` | in a private repository, whether the stored sources are committed | `literature.sources_in_git`, and the line out of `.gitignore` |
| `repository.github_actions` | whether check runs on each push | the workflow `init --github-actions` writes |
| `earlier_work` | whether the authors published on these data before | nothing; the related-outputs skill follows |

The answers for a cohort study whose journal is chosen:

```yaml
schema: manuscript-guard/setup/1
start: markdown
title: "Statins and liver injury: a cohort study"
language: en-GB
study_type: cohort
reporting_guideline: [STROBE, RECORD]
journal: {name: "BMJ Open"}
authors:
  - given: Ada
    family: Byron
    affiliations: ["Department of Pharmacology, University of Examples, Caen, France"]
    corresponding: true
    orcid: 0000-0002-1825-0097
declarations: later
statistician: Byron
ethics_lead: later
analysis: r
data: {where: project, folder: data, publishable: false}
registration: later
repository: {git: true, visibility: private, sources_in_git: false, github_actions: true}
earlier_work: false
```

An answer the tool cannot take keeps its question open, with the reason: an ORCID iD whose
check digit is wrong, no corresponding author, a statistician who is not among the authors, a
data folder that is one of the toolkit's own, a title `init` would refuse.

## What `apply` writes, and what it never does

Nothing is written while a question is open. Then every change is worked out and read back
first, so that a setting `paper.yaml` would refuse stops all of it, with the files as they
were; so does a Word paper where no pandoc is found to bring it in. `apply` writes, in
order: the project (`init`), the git repository, the settings of `paper.yaml`, the title in
the manuscript's header, `authors.yaml`, the journal's profile, `.gitignore`, the workflow,
and last the date it did so, as `applied_on` in `design/setup.yaml`.

- It fills only what is blank. A setting `paper.yaml` holds already is kept and said; a
  change is `manuscript-guard set`'s, whose guard asks before a stage moves back, a guideline
  goes or a journal is replaced. In a project already under way, the same conversation fills
  its blanks: a placeholder `authors.yaml`, no English, no design.
- It registers no vault. Data held apart from the agent are registered by a person, where the
  data can be read, with `vault init` ([the vault](vault.md)).
- It fills no journal profile. The profile it starts is the annotated template, which the
  journal-profile skill fills from the journal's own instructions page.
- It sends nothing anywhere, and runs no program but `git init`, pandoc to bring a Word paper
  in, and for an R analysis `Rscript`, to ask which packages it has; each with a time limit.

`design/setup.yaml` stays in the project as the record of what was chosen at the start.
`paper.yaml` and `authors.yaml` hold the settings, and every check reads them; nothing is
checked against the record.

## What comes next

`apply` ends with the steps that follow, each with the skill that takes it on: the journal's
profile filled from its page, or the journal chosen with a shortlist; the data found, or
registered by a person in the vault, or taken in from a site; the analysis plan written
section by section; the reporting checklists retrieved; the earlier outputs recorded; the
first analysis script. `manuscript-guard next` says, from then on, what to do now.

## The JSON

`setup questions --json` prints `manuscript-guard/setup-questions/1`: the `folder`, whether
the `project` is `new` or `under-way`, `ready` once nothing is open, the `questions`, those
`waiting` on another's answer with what they wait `on`, what is `known` from the folder, and
once ready the steps `after`. A question has its `id`, `question`, `why`, `kind` (`choice`,
`several`, `text`, `number`, `yes-no`, `authors`), its `options`, each a `value`, `label` and
`effect`, the value `recommended` or null, what an answer outside the options is (`other`),
how many options to `shortlist` once the study is described, an `example` of the answer as
written, and the `problem` with the answer written, if any.

`setup apply --json` prints `manuscript-guard/setup-applied/1`: `dry_run`, `ok`, why it
`refused` and what is still `open`, what was `written` and `kept`, each a `file`, `what` and
`why`, the `notes`, the `tools` this machine has or lacks, and the steps `after`. Its exit is 0
once written, 1 where a question is open or an answer cannot be written, and 2 where the
folder is inside another project or a file of it cannot be read.

Both schemas are in `src/manuscript_guard/contracts/schemas/`, beside the answers file's own,
`setup.schema.json`. What setup does not do is in DESIGN.md, under Known gaps.

[Back to the README](../README.md)
