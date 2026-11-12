# For supervisors and research groups

This page is for a supervisor, a principal investigator or a group that keeps several papers with manuscript-guard:
what it gives you across them, and what stays yours. A student starting a first project reads
[getting started](getting-started.md) instead.

## One layout for every paper

`manuscript-guard init my-paper` writes the same project each time:

| File or folder | What it holds |
|---|---|
| `paper.yaml` | the stage, the target journal, the reporting guideline and the study design, and the data custodian's rules where there are any |
| `authors.yaml` | the authors, their affiliations, and who signs off what (below) |
| `design/plan.md` | the analysis plan, written before the analysis |
| `results/` | what the analysis writes, never edited by hand |
| `manuscript/main.md` | the manuscript, its numbers written as bindings to the results |
| `literature/` | the ledger of values quoted from papers, and the references |
| `AGENTS.md` | the rules of the project on one page, for any agent working there |

A paper you open for the first time is laid out like the last one, and `manuscript-guard next`
says where it stands and what comes next.

## The check on every push

In a paper's repository:

```bash
manuscript-guard init --github-actions
```

writes a workflow that runs `check` on each push to the default branch and on each pull
request, at the stage `paper.yaml` declares, and builds the documents where it passes. A
student or a co-author sees on the pull request which findings their change opened, and the
run keeps the report and the .docx for anyone who can read the repository. No gate is softened
there, and no secret is needed ([checking a paper in GitHub Actions](github-actions.md)).

A badge in the paper's README can show what the last run on the default branch found, as
"manuscript-guard check | passes at stage drafting". It is off until the repository variable
`MANUSCRIPT_GUARD_BADGE` is set to `true`, and it works for a public repository only. Before
making one public, look at `literature/sources/`: it holds the copies of the works the paper
cites, paywalled ones among them ([the badge](github-actions.md#the-badge)). A pass means that
no finding due at that stage is open; at `design` that is almost nothing.

## Co-authors

What no gate can check is whether a sentence says what its source says. The checker puts that
question to each co-author on a page of their own, which opens offline in any current browser:

```bash
manuscript-guard checker build --all     # one file per author, to send each
manuscript-guard checker status          # outstanding, stale, and who disagrees
manuscript-guard checker recap           # who checked what, into checks/recap.md
```

Each answer carries the digest of what its author saw, so an answer about a sentence that has
changed since no longer counts. The record says who looked, at what, when, and what they said;
it does not say that they read correctly. Co-authors who edit in Word stay in Word: `import`
brings their edits back to the source and files each comment as a finding to answer
([working with co-authors](co-authors.md)).

## Approvals and sign-offs

```bash
manuscript-guard approve --as "<author>"
manuscript-guard sign --as "<person>" --finding <id>
```

`approve` records an author's approval of the manuscript as it stands, and `submit` says who
has not approved, or who approved a version that has changed since. `sign` records a named
person's sign-off of a finding that only they may close: a warning about a fitted model, for
the statistician; the journal's rules that no gate checks, for the corresponding author; a
model provider the manuscript may be sent to, for the data custodian. `authors.yaml` names
these people under `roles:`, and the corresponding author is the one marked
`corresponding: true`. The finding's hint gives the id.

Each is that person's own act. Under Claude Code the plugin's hooks put it to you before an
agent runs it; under Codex they refuse it, and the person runs it at a terminal
([agent tools](agent-tools.md)).

## Review panels

Before submission, G11 asks that a recorded panel has read the manuscript and that its major
findings are answered. The panel can be people, such as an internal reviewer or a lab meeting,
an agent, or models from several providers. Sending an unpublished manuscript to a provider is
the authors' decision: with the models listed under `review: models:` in `paper.yaml`,
`manuscript-guard review --run --dry-run` writes what would be sent where, and sends nothing
([a review panel read by several models](review-panel.md)), and [what a provider
keeps](review-panel.md#what-a-provider-keeps) says what each provider's terms let it keep.

## Data with a custodian

Where the data come with a custodian's rules, `paper.yaml` declares them, as
`custodian: {minimum_cell_count: 10}`, and from the internal-review stage `check` fails a bound
count printed below that minimum. The [vault](vault.md) registers the folder that holds the
data, which the operating system keeps from the agent: the agent writes the analysis against a
synthetic copy, a person runs it on the real data, and what the run wrote leaves the vault only
when a person releases it.

```bash
manuscript-guard vault init /secure/extract cohort.csv --as "<you>"
manuscript-guard vault check
```

manuscript-guard does not keep the agent out. A second account, a container or the folder's
permissions do; `vault check` says whether this session can read the data.

## What stays yours

- **The design and the methods.** G12 holds that there is a plan, that it says something, and
  that a change after the first results is said under Deviations; whether it was a good plan is
  for you and the statistician. G15 holds a model to the variables it was declared with, not to
  the question.
- **The code.** What an agent wrote, and what a run on the real data wrote before it leaves the
  vault, is read by a person.
- **The data's terms.** Nothing here makes a setup lawful under data-protection law or a
  data-use agreement; that is for the custodian, the data protection officer or the ethics board.
- **What a pass means.** That no finding due at the stage is open. Neither the badge, nor the
  checker's record, nor a panel's reading is evidence that the paper is right.

For a manuscript written some other way, see [auditing a paper you already wrote](audit.md);
for an editor's or a referee's reading of someone else's, [for editors and
reviewers](refereeing.md).

[Back to the README](../README.md)
