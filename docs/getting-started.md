# Getting started

This page is for someone new to keeping a study in code: a PhD student, a clinician writing a
first paper, anyone who has written papers in Word and typed the numbers in by hand. It says
what you need, who decides what, what to do in your first hour, and what you still check
yourself. If you have kept an analysis in code before, the README's
[Quick start](../README.md#quick-start) may be all you need.

## What you need

To check a paper you have already written, nothing has to be installed. The
[audit page](audit-page.md) runs `manuscript-guard audit` on a .docx in a web browser, and
the paper is read there, not uploaded. At a terminal, [uv](https://docs.astral.sh/uv/) runs
the same audit in one line, and fetches a Python if there is none:

```bash
uvx manuscript-guard audit paper.docx
```

A paper written with manuscript-guard from the start needs more, and some of it is new to
most authors:

- Python 3.10 or later for manuscript-guard itself, and Python or R for the analysis.
  The analysis is a script that reads the data and writes its results, and the manuscript's
  numbers come from those results rather than from a table copied by hand. An analysis in R
  needs the [R emitter](install.md#the-r-emitter-only-if-your-analysis-is-in-r).
- git, which keeps every version of the project, so that you, a co-author or a reviewer
  can see later what changed and when.
- pandoc, which turns the Markdown manuscript into the .docx you send.
  [Installing](install.md) lists the other tools, each needed for one step only.
- A terminal. Each step is a command. You type it, or an agent types it and you read what
  it did.

The work goes best with an agent tool such as Claude Code or Codex, which loads the skills that
carry each step and the hooks that catch a mistake as it is made ([agent tools](agent-tools.md)).
No check needs one, and a project can be run by hand from start to end.

You will read and change code. An agent can write much of it, but the analysis is yours, and
so is reading what the agent wrote before you rely on it.

## Who decides what

The README's [who does what](../README.md#who-does-what) puts it in one table: an agent
drafts and runs, the gates decide from the project's records and ask no model anything, and a
person makes the calls only a person may make. What matters on the first day is where the
gates stop. A gate can say that a number is the one the analysis wrote, or that a quote is in
the stored source. It cannot say that the analysis was the right one, or that the source
supports the sentence. Those are judgements for people, and the tool records who made them
and when.

## Your first hour

### 1. Your own paper

Give the audit page, or `uvx manuscript-guard audit`, a paper you wrote.
It reads the numbers against each other, the Abstract against the Results, the words and the
reference list, and says where each finding is. A number that agrees with another tells you
little about where it came from: [auditing a paper you already wrote](audit.md) says how
little, and what to do with what it finds.

### 2. The worked example

[`example/`](../example/) is a synthetic study kept as a project
from its plan to its build. It is in the repository and not in the installed package, so it
needs a clone, and a Python with manuscript-guard, statsmodels for its model and matplotlib
for its figure:

```bash
pip install manuscript-guard statsmodels matplotlib
git clone https://github.com/BasileChretien/manuscript-guard
cp -r manuscript-guard/example my-example && cd my-example
python analysis/00_simulate.py && python analysis/01_disproportionality.py && python figures/forest.py
manuscript-guard check
manuscript-guard build --offline
```

Then open `manuscript/main.md`, type a number over one of the `{{results.…}}` bindings, and
run `manuscript-guard check` again. It names the number, its line and column, and how to give
it a source. `manuscript-guard explain manuscript/main.md` prints every number in the file and
the rule that classified it.

### 3. Your own project

```bash
pip install manuscript-guard
manuscript-guard init my-paper
cd my-paper
manuscript-guard next
```

`init` writes the project: `paper.yaml`, the authors, an analysis plan to fill in, the
manuscript, the ledger of values quoted from the literature, and an `AGENTS.md` that gives
any agent working there the rules on one page. `next` says what to do now, with the command to
run. With the plugin in Claude Code or Codex ([agent tools](agent-tools.md)), ask the agent to
work through the paper with you: the `guide` skill reads `next` and puts each choice to you as
numbered options.

A new project starts at the `design` stage, and `check` fails nothing on the project as `init`
wrote it: what is not due yet is printed and counted. Each finding fails from the stage at
which it starts to matter ([stages](stages.md)), so the checks arrive as the paper does.

## What you still check yourself

- **That the design answers the question.** `check` holds the analysis to its plan. It does not
  say whether the plan was the right one; that is for you and your supervisor or statistician,
  before the analysis is written.
- **The code an agent wrote.** A script that runs and writes its results can still compute the
  wrong thing. `check` holds the results to the script that wrote them, not the script to what
  it should compute. Read it, or have someone read it.
- **That each sentence says what its source says.** A number can be right, its quote can be
  right, and the sentence around it can still name the wrong group or year. The
  [checker](co-authors.md#what-no-gate-can-check-the-checker) puts that question to your
  co-authors, one page each. It records who looked and what they said, not that they read
  correctly.
- **What a passing check means.** That no finding due at the project's stage is open. It is not
  evidence that the paper is right ([status](../README.md#status)).

## Where next

- [For supervisors and research groups](teams.md): the same tool across a group's papers.
- [What to do next](next.md): how `next` decides what comes first.
- [Working with co-authors](co-authors.md): Word, comments, approvals and the checker.
- [For editors and reviewers](refereeing.md): reading someone else's manuscript.

[Back to the README](../README.md)
